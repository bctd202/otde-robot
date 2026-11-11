from datetime import timedelta
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.models import (AutomatedOptionMark, DebitSpreadAccount, DebitSpreadEvent, DebitSpreadPosition,
                           ForwardPaperAccount, ForwardPaperEvent, ForwardPaperPosition, SignalPerformance)
from app.services import debit_spread_account as sp
from app.services import debit_spread_runner as runner
from app.services.cost_model import CostPolicy
from app.services.debit_spread_math import entry_debit, liquidation, select_hedge
from app.services.retest_trials import code_hash
from test_forward_account import candidate, Quotes, START
from test_performance import database


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, 'debit_spread_enabled', True)
    monkeypatch.setattr(settings, 'market_data_provider', 'tastytrade')


class Pair:
    def __init__(self, at, *, ticker='SPY', long_bid=.40, long_ask=.45, short_bid=.10, short_ask=.12,
                 right='call', short_strike=102, **changes):
        long_symbol=f'{ticker}260803{right[0].upper()}00100000'
        short_symbol=f'{ticker}260803{right[0].upper()}{int(short_strike*1000):08d}'
        self.long=Quotes(at).quote.model_copy(update={'symbol':ticker,'option_symbol':long_symbol,
            'normalized_symbol':long_symbol,'right':right,'bid':long_bid,'ask':long_ask})
        self.short=Quotes(at).quote.model_copy(update={'symbol':ticker,'option_symbol':short_symbol,
            'normalized_symbol':short_symbol,'strike':short_strike,'right':right,
            'bid':short_bid,'ask':short_ask,**changes})
        self._instrument_cache={ticker:(at,[{'symbol':q.option_symbol,'expiration-date':q.expiration.isoformat(),
            'strike-price':str(q.strike),'option-type':q.right[0].upper()} for q in (self.long,self.short)])}
        self.rows=[self.long,self.short]
        self.requests=0

    def status(self):return SimpleNamespace(status='healthy',mode='live')
    def cached_option_chain(self,*_):return self.rows
    def option_chain(self,*_):
        self.requests+=1
        raise AssertionError('No new provider requests allowed')


def activate(db):return sp.activate(db,revision='a'*40,now=START-timedelta(hours=1,seconds=1))


def opened(db):
    activate(db);trade=candidate(db)
    sp.advance(db,Pair(START),now=START)
    later=START+timedelta(seconds=2)
    sp.advance(db,Pair(later),now=later)
    db.flush()
    assert db.scalar(select(DebitSpreadPosition)).status=='OPEN'
    return trade


def test_disabled_and_enabled_reads_never_fund_or_collect(monkeypatch):
    with database()() as db:
        monkeypatch.setattr(get_settings(),'debit_spread_enabled',False)
        class Bomb:
            def __getattr__(self,_):raise AssertionError('Disabled work touched provider')
        sp.advance(Bomb(),Bomb(),now=START)
        assert sp.summary(db)['status']=='NOT_ACTIVATED'
        with pytest.raises(ValueError):activate(db)
        monkeypatch.setattr(get_settings(),'debit_spread_enabled',True)
        assert sp.summary(db)['status']=='NOT_ACTIVATED'
        sp.advance(db,Bomb(),now=START)
        assert db.scalar(select(func.count()).select_from(DebitSpreadAccount))==0
        assert db.scalar(select(func.count()).select_from(DebitSpreadEvent))==0


def test_activation_is_once_explicit_prospective_and_frozen():
    with database()() as db:
        candidate(db)
        with pytest.raises(ValueError):sp.activate(db,revision='a'*40,now=START)
        account=sp.activate(db,revision='a'*40,now=START.replace(hour=21))
        old=json.dumps(account.policy,sort_keys=True)
        sp.activate(db,revision='b'*40,now=START.replace(hour=22))
        assert json.dumps(account.policy,sort_keys=True)==old
        assert account.policy['max_entry_cents']==25000
        assert account.policy['max_daily_debit_cents'] is None
        assert account.policy['max_positions']==10
        sp.advance(db,Pair(START+timedelta(days=1)),now=START+timedelta(days=1))
        assert db.scalar(select(func.count()).select_from(DebitSpreadPosition))==0
        assert sp.balance(db)==(200000,0,0)


@pytest.mark.parametrize('right,target,strikes,expected',[
 ('call',101.5,[103,101,102],102),('put',98.5,[97,99,98],98),
 ('call',100,[100,101],101),('call',110,[101,102],None),('put',90,[98,99],None)])
def test_strike_order_target_equal_rule_and_missing_hedge(right,target,strikes,expected):
    long=Pair(START,right=right).long
    chain=[long.model_copy(update={'strike':k,'option_symbol':str(k)}) for k in strikes]
    chosen=select_hedge(long,target,list(reversed(chain)))
    assert (chosen.strike if chosen else None)==expected


def test_hedge_never_uses_other_expiry_symbol_or_right():
    pair=Pair(START)
    for changes in ({'expiration':START.date()+timedelta(days=1)},{'symbol':'QQQ'},{'right':'put'}):
        assert select_hedge(pair.long,101,[pair.short.model_copy(update=changes)]) is None


def test_pair_cash_math_costs_and_short_buyback_outflow():
    cost=CostPolicy()
    assert entry_debit(.45,.10,cost)==4000
    assert liquidation(.75,.20,cost)==5200
    assert liquidation(0,3,cost)==-30200
    assert liquidation(.75,.20,cost)-entry_debit(.45,.10,cost)==1200


def test_later_quote_fill_exit_completed_clock_negative_flow_and_no_requests():
    with database()() as db:
        trade=opened(db);p=db.scalar(select(DebitSpreadPosition))
        assert p.detail['entry_debit_cents']==4000
        trade.exit_reason='STOP';trade.exit_at=START+timedelta(minutes=5)
        # Legacy timestamp denotes candle START; new account must wait for completion.
        sp.advance(db,Pair(trade.exit_at),now=trade.exit_at)
        assert p.status=='OPEN'
        completed=trade.exit_at+timedelta(minutes=1)
        source=Pair(completed,long_bid=0,long_ask=.01,short_bid=2.9,short_ask=3)
        sp.advance(db,source,now=completed)
        assert p.status=='EXIT_PENDING'
        sp.advance(db,Pair(completed+timedelta(seconds=2),long_bid=0,long_ask=.01,
                         short_bid=2.9,short_ask=3),now=completed+timedelta(seconds=2))
        assert p.status=='CLOSED'
        assert p.detail['exit_credit_cents']==-30200
        assert sp.balance(db)==(165800,0,-34200)
        assert source.requests==0


@pytest.mark.parametrize('changes',[
 {'received_at':None},{'receipt_basis':'UNKNOWN'}, {'bid_timestamp':START},
 {'received_at':START-timedelta(seconds=90)}, {'ask_timestamp':START+timedelta(minutes=1)},
 {'data_mode':'delayed'},{'option_symbol':'SPY260803C00103000'},
 {'received_at':START+timedelta(seconds=3)},
])
def test_stale_future_repeated_missing_receipt_or_wrong_contract_never_fills(changes):
    with database()() as db:
        activate(db);candidate(db)
        sp.advance(db,Pair(START),now=START)
        sp.advance(db,Pair(START+timedelta(seconds=2),**changes),now=START+timedelta(seconds=2))
        p=db.scalar(select(DebitSpreadPosition));assert p.status=='PENDING_ENTRY'
        sp.advance(db,Pair(START+timedelta(seconds=122)),now=START+timedelta(seconds=122))
        assert p.status=='SKIPPED' and sp.balance(db)==(200000,0,0)


def test_listing_identity_frozen_even_when_nearer_quote_missing():
    with database()() as db:
        activate(db);candidate(db)
        first=Pair(START);first.rows=[first.long]
        sp.advance(db,first,now=START)
        p=db.scalar(select(DebitSpreadPosition));assert p.detail['short']['strike']==102
        later=Pair(START+timedelta(seconds=2),short_strike=103)
        sp.advance(db,later,now=START+timedelta(seconds=2))
        assert p.status=='PENDING_ENTRY'
        sp.advance(db,Pair(START+timedelta(seconds=3)),now=START+timedelta(seconds=3))
        assert p.status=='OPEN' and p.detail['short']['strike']==102


def test_quotes_without_cached_listings_cannot_invent_nearest_listed_strike():
    with database()() as db:
        activate(db);candidate(db);source=Pair(START);source._instrument_cache={}
        sp.advance(db,source,now=START)
        assert db.scalar(select(DebitSpreadPosition)).status=='SKIPPED'
        assert sp.balance(db)==(200000,0,0)


def test_missing_exit_stays_unknown_expiry_not_zero_and_no_backfill():
    with database()() as db:
        trade=opened(db);trade.exit_reason='TARGET';trade.exit_at=START+timedelta(minutes=1)
        at=trade.exit_at+timedelta(minutes=1)
        sp.advance(db,None,now=at)
        sp.advance(db,None,now=at+timedelta(seconds=181))
        p=db.scalar(select(DebitSpreadPosition));assert p.status=='UNPRICED'
        sp.advance(db,Pair(at+timedelta(seconds=182)),now=at+timedelta(seconds=182))
        assert p.status=='UNPRICED'
        result=sp.summary(db,now=at+timedelta(seconds=182))
        assert result['equity_cents'] is None and result['available_cents'] is None
        assert sp.balance(db)==(196000,0,0)


def test_live_open_at_expiry_is_unknown_not_assignment_or_cash_credit():
    with database()() as db:
        opened(db)
        sp.advance(db,None,now=START.replace(hour=20))
        p=db.scalar(select(DebitSpreadPosition));assert p.status=='EXPIRED_UNRESOLVED'
        assert sp.balance(db)==(196000,0,0)


def test_restart_idempotent_read_nonmutation_and_protected_sources():
    local=database()
    with local() as db:
        opened(db);db.commit()
    with local() as db:
        before=db.scalar(select(func.count()).select_from(DebitSpreadEvent))
        sp.advance(db,Pair(START+timedelta(seconds=2)),now=START+timedelta(seconds=2))
        changes=db.connection().connection.driver_connection.total_changes
        for _ in range(2):sp.summary(db,now=START+timedelta(seconds=2))
        assert changes==db.connection().connection.driver_connection.total_changes
        assert db.scalar(select(func.count()).select_from(DebitSpreadEvent))==before
    assert code_hash()=='4fe8e0a500a9d2440e6e0de0bb93bcd46f7c006abf78710618298318ec14cc57'



def test_optional_failure_rolls_back_only_its_savepoint(monkeypatch):
    with database()() as db:
        trade=candidate(db);db.flush()
        def broken(*args,**kwargs):
            trade.score=0;db.flush();raise RuntimeError('synthetic optional failure')
        monkeypatch.setattr(sp,'advance',broken)
        runner.run(db,Pair(START),now=START)
        assert db.get(SignalPerformance,trade.signal_id).score==90
        assert db.scalar(select(func.count()).select_from(AutomatedOptionMark))==1


def test_all_in_cap_and_settled_cash_not_daily_debit_cap():
    with database()() as db:
        activate(db);candidate(db)
        sp.advance(db,Pair(START),now=START)
        sp.advance(db,Pair(START+timedelta(seconds=2),long_bid=2.8,long_ask=2.9),now=START+timedelta(seconds=2))
        p=db.scalar(select(DebitSpreadPosition));assert p.status=='SKIPPED'
        assert sp.balance(db)==(200000,0,0)


def test_unresolved_matched_entry_is_not_removed_from_denominator():
    with database()() as db:
        trade=opened(db)
        mark=db.scalar(select(AutomatedOptionMark))
        # Independent baseline entry exists; pending/unknown exits must stay paired.
        db.add(ForwardPaperAccount(key=sp.BASELINE,activated_at=START-timedelta(hours=1),
            processed_at=START,mark_watermark=0,revision=0,policy={}))
        db.flush()
        db.add(ForwardPaperPosition(account_key=sp.BASELINE,signal_id=trade.signal_id,entry_mark_id=mark.id,
            status='UNPRICED',first_seen_at=START,detail={'entry_at':START.isoformat()}))
        db.flush()
        assert sp.summary(db,now=START+timedelta(seconds=3))['matched']['entered_pairs']==0
        pos=db.scalar(select(ForwardPaperPosition))
        db.add(ForwardPaperEvent(account_key=sp.BASELINE,event_key='entry',occurred_at=START,
            kind='ENTRY',settled_cents=-4750,unsettled_cents=0,realized_cents=0,fee_cents=150,
            detail={'position_id':pos.id}))
        db.flush()
        result=sp.summary(db,now=START+timedelta(seconds=3))
        assert result['matched']['entered_pairs']==1
        assert result['matched']['unresolved_pairs']==1
        assert not result['matched']['complete']


class ManyPairs:
    def __init__(self, at, tickers, **kwargs):
        self.pairs={t:Pair(at,ticker=t,**kwargs) for t in tickers}
        self._instrument_cache={t:p._instrument_cache[t] for t,p in self.pairs.items()}
    def status(self):return SimpleNamespace(status='healthy',mode='live')
    def cached_option_chain(self,ticker,*_):return self.pairs[ticker].rows
    def option_chain(self,*_):raise AssertionError('Cache-only account requested data')


def test_ten_slots_more_than_three_and_no_five_hundred_daily_cap():
    tickers=['SPY','QQQ','IWM','AAPL','MSFT','NVDA','AMZN','META','TSLA','AMD','GLD']
    with database()() as db:
        activate(db)
        for t in tickers:candidate(db,name=t,ticker=t)
        sp.advance(db,ManyPairs(START,tickers),now=START)
        later=START+timedelta(seconds=2)
        sp.advance(db,ManyPairs(later,tickers),now=later)
        states=list(db.scalars(select(DebitSpreadPosition)))
        assert sum(p.status=='OPEN' for p in states)==10
        assert sum(p.status=='SKIPPED' for p in states)==1
    # Four $196 all-in reservations fit the account, despite exceeding $500 in entries.
    with database()() as db:
        activate(db)
        for t in tickers[:4]:candidate(db,name=t,ticker=t)
        sp.advance(db,ManyPairs(START,tickers[:4],short_strike=105),now=START)
        later=START+timedelta(seconds=2)
        sp.advance(db,ManyPairs(later,tickers[:4],short_strike=105,long_bid=2.3,long_ask=2.4,
                                short_bid=.50,short_ask=.55),now=later)
        assert sp.balance(db)[0]==200000-4*19500
        assert sum(p.status=='OPEN' for p in db.scalars(select(DebitSpreadPosition)))==4


@pytest.mark.parametrize('ask,expected',[(2.54,'OPEN'),(2.5401,'SKIPPED')])
def test_exact_all_in_ceiling_without_rounding_over_budget_down(ask,expected):
    with database()() as db:
        activate(db);candidate(db)
        sp.advance(db,Pair(START,short_strike=105),now=START)
        later=START+timedelta(seconds=2)
        sp.advance(db,Pair(later,short_strike=105,long_bid=2.50,long_ask=ask),now=later)
        assert db.scalar(select(DebitSpreadPosition)).status==expected


def test_positive_proceeds_unsettled_until_eligible_day():
    with database()() as db:
        trade=opened(db);trade.exit_reason='TARGET';trade.exit_at=START+timedelta(minutes=5)
        at=trade.exit_at+timedelta(minutes=1)
        sp.advance(db,Pair(at),now=at)
        later=at+timedelta(seconds=2)
        sp.advance(db,Pair(later,long_bid=.75,long_ask=.80,short_bid=.18,short_ask=.20),now=later)
        p=db.scalar(select(DebitSpreadPosition));assert p.status=='UNSETTLED'
        assert sp.balance(db)==(196000,5200,1200)
        sp.advance(db,None,now=START+timedelta(days=1))
        assert p.status=='CLOSED' and sp.balance(db)==(201200,0,1200)


def test_put_mapping_same_expiry_and_pending_invalidation():
    with database()() as db:
        activate(db);trade=candidate(db);trade.direction='PUT';trade.target_price=98.5;trade.stop_price=101
        mark=db.scalar(select(AutomatedOptionMark));mark.right='put'
        mark.option_symbol=mark.normalized_option_symbol='SPY260803P00100000'
        sp.advance(db,Pair(START,right='put',short_strike=98),now=START)
        p=db.scalar(select(DebitSpreadPosition));assert p.detail['short']['strike']==98
        assert p.detail['short']['expiration']==p.detail['long']['expiration']
        trade.exit_reason='STOP';trade.exit_at=START+timedelta(seconds=1)
        later=START+timedelta(seconds=2)
        sp.advance(db,Pair(later,right='put',short_strike=98),now=later)
        assert p.status=='SKIPPED' and sp.balance(db)==(200000,0,0)


def test_misaligned_valid_source_times_cannot_form_a_package():
    with database()() as db:
        activate(db);candidate(db)
        sp.advance(db,Pair(START),now=START)
        later=START+timedelta(seconds=10)
        sp.advance(db,Pair(later,received_at=later-timedelta(seconds=3)),now=later)
        assert db.scalar(select(DebitSpreadPosition)).status=='PENDING_ENTRY'


def test_no_settled_funds_no_entry_and_no_new_financing():
    with database()() as db:
        activate(db);sp.event(db,'RESEARCH_FIXTURE_CASH_LIMIT','limited',START,settled=-198000)
        candidate(db);sp.advance(db,Pair(START),now=START)
        later=START+timedelta(seconds=2)
        sp.advance(db,Pair(later),now=later)
        p=db.scalar(select(DebitSpreadPosition));assert p.detail['reason']=='INSUFFICIENT_SETTLED_CASH'
        assert sp.balance(db)==(2000,0,0)


def test_no_second_ticker_day_setup_after_first_skipped():
    with database()() as db:
        activate(db);candidate(db,'first')
        source=Pair(START);source._instrument_cache={}
        sp.advance(db,source,now=START)
        db.scalar(select(AutomatedOptionMark)).position_key='ONE_MIN_0DTE:SPY:first'
        db.flush()
        candidate(db,'second',now=START+timedelta(seconds=2))
        later=START+timedelta(seconds=2)
        sp.advance(db,Pair(later),now=later)
        states=list(db.scalars(select(DebitSpreadPosition)))
        assert len(states)==2 and all(p.status=='SKIPPED' for p in states)
        assert states[-1].detail['reason']=='FIRST_TICKER_DAY_ALREADY_RECORDED'


def test_scanner_outputs_and_requests_same_when_disabled_enabled_or_optional_failure(monkeypatch):
    from app.services import signal_engine as engine
    from test_signal_engine import Provider, candidate as scan_candidate
    from app.db.models import ScannerRuntime
    outcomes=[]
    for mode in ('disabled','enabled','failure'):
        monkeypatch.setattr(get_settings(),'debit_spread_enabled',mode!='disabled')
        trace=[]
        monkeypatch.setattr(engine,'rank_parlays',lambda *a,**k:trace.append('baseline') or [scan_candidate('PASS')])
        monkeypatch.setattr(engine,'rank_structured_intraday',lambda *a,**k:trace.append('structured') or [])
        monkeypatch.setattr(engine,'track_candidates',lambda *a,**k:None)
        monkeypatch.setattr(engine,'track_lottery_scan',lambda *a,**k:trace.append('lotto') or [])
        if mode=='failure':
            def fail(*a,**k):raise RuntimeError('Optional synthetic failure')
            monkeypatch.setattr(sp,'advance',fail)
        with database()() as db:
            scan=engine.run_signal_scan(db,Provider(),['SPY'])
            state=db.get(ScannerRuntime,'parlay')
            outcomes.append((trace,[(c['symbol'],c['signal_status'],c['score']) for c in scan.candidates],
                state.status,state.last_error,db.scalar(select(func.count()).select_from(DebitSpreadAccount)),
                db.scalar(select(func.count()).select_from(DebitSpreadEvent))))
    assert outcomes[0]==outcomes[1]==outcomes[2]
    assert outcomes[0][-2:]==(0,0)


@pytest.mark.parametrize('field,value', [('right','put'),('ticker','QQQ'),('strategy_mode','STRUCTURED_INTRADAY'),
                                        ('verification_status','unverified')])
def test_original_mark_must_agree_with_signal_identity(field,value):
    with database()() as db:
        activate(db);candidate(db)
        mark=db.scalar(select(AutomatedOptionMark));setattr(mark,field,value)
        sp.advance(db,Pair(START),now=START)
        assert db.scalar(select(DebitSpreadPosition)).detail['reason']=='OUTSIDE_FROZEN_INPUT_POLICY'
        assert sp.balance(db)==(200000,0,0)


def test_listing_decision_evidence_survives_later_cache_changes():
    with database()() as db:
        activate(db);candidate(db);source=Pair(START)
        sp.advance(db,source,now=START)
        p=db.scalar(select(DebitSpreadPosition));frozen=json.dumps(p.detail['listing_evidence'],sort_keys=True)
        source._instrument_cache={}
        later=START+timedelta(seconds=2)
        sp.advance(db,Pair(later),now=later)
        assert p.status=='OPEN'
        assert json.dumps(p.detail['listing_evidence'],sort_keys=True)==frozen
        request=db.scalar(select(DebitSpreadEvent).where(DebitSpreadEvent.kind=='ENTRY_REQUEST'))
        assert json.dumps({k:v for k,v in request.detail['listing_evidence'].items() if k!='instruments'},sort_keys=True)==frozen
        assert len(request.detail['listing_evidence']['instruments'])==2


def test_bounded_watermark_pagination_and_quote_denominators():
    tickers=['T'+chr(65+i//26)+chr(65+i%26) for i in range(45)]
    with database()() as db:
        activate(db)
        for t in tickers:candidate(db,name=t,ticker=t)
        sp.advance(db,ManyPairs(START,tickers),now=START)
        assert db.scalar(select(func.count()).select_from(DebitSpreadPosition))==40
        later=START+timedelta(seconds=2)
        sp.advance(db,ManyPairs(later,tickers),now=later)
        result=sp.summary(db,page=2,now=later)
        assert result['opportunities']==45 and result['pages']==3
        assert len(result['positions'])==20 and result['positions'][0]['id']==25
        assert all('listing_evidence' not in p for p in result['positions'])
        assert result['entry_quote_coverage']=={'requested':10,'quoted':10,'filled':10}
        assert result['skips']==35


def test_chart_payload_retains_daily_endpoints_and_latest_day_without_losing_archive():
    from app.db.models import DebitSpreadSnapshot
    with database()() as db:
        activate(db)
        for i in range(80):
            db.add(DebitSpreadSnapshot(account_key=sp.KEY,at=START+timedelta(minutes=i),
                trading_date=START.date(),cash=200000,equity=200000,unknown=0))
        for i in range(2):
            db.add(DebitSpreadSnapshot(account_key=sp.KEY,at=START+timedelta(days=1,minutes=i),
                trading_date=(START+timedelta(days=1)).date(),cash=200000,equity=200000,unknown=0))
        db.flush()
        result=sp.summary(db,now=START+timedelta(days=1,minutes=2))
        assert len(result['history'])==3
        assert db.scalar(select(func.count()).select_from(DebitSpreadSnapshot))==83
