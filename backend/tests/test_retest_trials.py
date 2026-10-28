from datetime import datetime, timedelta
from contextlib import nullcontext
from types import SimpleNamespace
import json

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.session import Base
from app.db.models import (ForwardPaperAccount, ForwardPaperEvent, RetestAccount, RetestEvent,
    RetestObservation, RetestOpportunity, RetestPosition, RetestRun)
from app.schemas.market import ParlayCandidateOut
from app.services import retest_trials as trial
from app.services.forward_account import KEY as MAIN_KEY, ensure_account
from app.services.retest_report import summary
from test_retest_research import BASE, candle, quote

ACTIVATION = BASE.replace(hour=12)


@pytest.fixture
def db(monkeypatch):
    engine=create_engine('sqlite://'); Base.metadata.create_all(engine)
    monkeypatch.setattr(trial,'configuration',lambda:{'provider':'tastytrade','paper_only':True,'universe':['SPY']})
    with Session(engine) as session:
        ensure_account(session, ACTIVATION-timedelta(minutes=1)); session.commit()
        yield session


def activate(db):
    value=trial.activate(db,revision='a'*40,now=ACTIVATION); db.commit(); return value


def candidate(ticker='SPY', mode='ONE_MIN_0DTE', ask=.48):
    q=quote(BASE, symbol=ticker, option_symbol=f'{ticker}261027C00100000', ask=ask,
        bid=ask-.02, actionable=True, normalized_symbol=f'{ticker}261027C00100000',
        verification_status='verified', verification_reason='synthetic verified')
    if mode=='STRUCTURED_INTRADAY':
        q=q.model_copy(update={'expiration':BASE.date()+timedelta(days=7),
            'option_symbol':f'{ticker}261103C00100000','normalized_symbol':f'{ticker}261103C00100000'})
    return ParlayCandidateOut(symbol=ticker,rank='PLAY',direction='call',signal_status='BUY',
        score=90,score_label='PLAY',underlying_price=100.2,contract=q,entry_low=ask-.04,
        entry_high=ask+.02,no_chase_price=ask+.10,underlying_trigger=100,underlying_invalidation=99,
        first_underlying_target=103,generated_at=BASE+timedelta(minutes=1,seconds=5),
        data_freshness='live_current',primary_action='Synthetic test',actionable=True,
        input_evidence={'input_version':'current-session-v2','session_date':BASE.date().isoformat()},
        strategy_mode=mode,strategy_version='parlay-v1-session-v2' if mode=='ONE_MIN_0DTE' else 'structured-intraday-v1-session-v2')


class Feed:
    def __init__(self,candidates=None):
        self.candidates=candidates or [candidate()]; self.now=BASE; self.bars=[]; self.calls=0; self.remaining=120
    def status(self):return SimpleNamespace(status='healthy',mode='live',provider='tastytrade')
    def cached_option_chain(self,symbol,expiration):
        return [c.contract.model_copy(update={'timestamp':self.now,'bid_timestamp':self.now,
            'ask_timestamp':self.now,'received_at':self.now}) for c in self.candidates
                if c.symbol==symbol and c.contract.expiration==expiration]
    def cached_candles(self,symbol):return [b.model_copy(update={'symbol':symbol}) for b in self.bars]
    def option_chain(self,*args):self.calls+=1; return self.cached_option_chain(*args)
    def budget_status(self):return {'remaining':self.remaining}
    def research_request_reserve(self,reserve):return nullcontext()


def tick(db,feed,minute,candidates=(),bar=None,quote_at=None):
    at=BASE+timedelta(minutes=minute)
    feed.now=quote_at or at+timedelta(minutes=1,seconds=5)
    feed.bars.append(bar or candle(minute,low=100.1 if minute!=1 else 99.9))
    capture={c.symbol:{'bars':[b.model_copy(update={'symbol':c.symbol}).model_dump(mode='json') for b in feed.bars],
                      'planning_risk':2} for c in feed.candidates}
    trial.process(db,feed,candidates=candidates,evaluation_at=at,capture=capture,
                  now=at+timedelta(minutes=1,seconds=5))
    db.commit()


def position(db,arm='control',scenario='base',ticker='SPY'):
    return db.scalar(select(RetestPosition).join(RetestOpportunity).where(
        RetestPosition.arm==arm,RetestPosition.scenario==scenario,RetestOpportunity.ticker==ticker))


def test_read_and_scanner_do_not_activate(db):
    before=db.scalar(select(func.count()).select_from(ForwardPaperEvent))
    assert summary(db)['status']=='NOT_ACTIVATED'
    trial.process(db,now=BASE)
    assert db.scalar(select(func.count()).select_from(RetestRun))==0
    assert db.scalar(select(func.count()).select_from(RetestEvent))==0
    assert db.scalar(select(func.count()).select_from(ForwardPaperEvent))==before


def test_explicit_one_time_activation_preserves_main_and_has_four_independent_accounts(db):
    original=json.dumps(db.get(ForwardPaperAccount,MAIN_KEY).policy,sort_keys=True)
    run=activate(db)
    assert len(run.policy['sessions'])==60
    assert trial.activate(db,revision='b'*40,now=ACTIVATION+timedelta(days=1)).activated_at==run.activated_at
    assert db.scalar(select(func.count()).select_from(RetestAccount))==4
    assert db.scalar(select(func.count()).select_from(RetestEvent).where(RetestEvent.kind=='FUNDING'))==4
    assert all(trial.balance(db,trial.account_key(a,s))==(200000,0) for a in trial.ARMS for s in trial.SCENARIOS)
    assert json.dumps(db.get(ForwardPaperAccount,MAIN_KEY).policy,sort_keys=True)==original
    assert summary(db,now=ACTIVATION)['verdict']=='INCONCLUSIVE'


def test_regular_session_activation_rejected(db):
    with pytest.raises(ValueError,match='outside'):
        trial.activate(db,revision='a'*40,now=BASE)


def test_paired_flow_and_frozen_stress_account_costs(db):
    activate(db); c=candidate(); feed=Feed([c])
    tick(db,feed,0,[c]); assert position(db).status=='PENDING_ENTRY'
    assert position(db,'treatment').status=='WAIT_RETEST'
    tick(db,feed,1)
    assert position(db).status=='OPEN' and position(db,'treatment').status=='PENDING_ENTRY'
    tick(db,feed,2)
    assert position(db,'treatment').status=='OPEN'
    assert position(db,'control','stress').detail['entry_debit_cents']-position(db).detail['entry_debit_cents']==200
    tick(db,feed,3)
    tick(db,feed,4,bar=candle(4,low=100.2,high=103.1,close=102.9))
    assert position(db).status==position(db,'treatment').status=='EXIT_PENDING'
    feed.candidates=[c.model_copy(update={'contract':c.contract.model_copy(update={'bid':.8,'ask':.85})})]
    tick(db,feed,5)
    assert position(db).status==position(db,'treatment').status=='UNSETTLED'
    assert position(db).detail['net_pnl_cents']-position(db,'control','stress').detail['net_pnl_cents']==400
    prior=trial.balance(db,trial.account_key('control','base'))
    assert prior[1]>0
    due=datetime.fromisoformat(position(db).detail['settles_at'])
    trial.process(db,now=due+timedelta(seconds=1)); db.commit()
    assert position(db).status=='CLOSED'
    after=trial.balance(db,trial.account_key('control','base'))
    assert after==(sum(prior),0)


def test_stress_changes_admission_not_just_reported_pnl(db):
    activate(db); c=candidate(ask=.96); feed=Feed([c]); tick(db,feed,0,[c])
    tick(db,feed,1)
    assert position(db).status=='OPEN'
    assert position(db,'control','stress').status=='SKIPPED'
    assert position(db,'control','stress').detail['reason']=='CAPACITY_SKIP'


def test_shared_ticker_gate_does_not_erase_one_minute_opportunity(db):
    activate(db); structured=candidate(mode='STRUCTURED_INTRADAY'); one=candidate(); feed=Feed([structured,one])
    tick(db,feed,0,[structured]); tick(db,feed,1,[one])
    rows=db.scalars(select(RetestOpportunity).order_by(RetestOpportunity.id)).all()
    assert [r.selected for r in rows]==[True,False]
    blocked=db.scalars(select(RetestPosition).where(RetestPosition.opportunity_id==rows[1].id,
                                                  RetestPosition.scenario=='base')).all()
    assert all(p.detail['reason']=='SHARED_TICKER_DAY_SELECTION' for p in blocked)
    raw=db.scalars(select(RetestPosition).where(RetestPosition.opportunity_id==rows[1].id,
                                              RetestPosition.scenario=='opportunity')).all()
    assert len(raw)==2 and all(p.account_key is None for p in raw)
    tick(db,feed,2,[one])
    assert db.scalar(select(func.count()).select_from(RetestOpportunity))==2


def test_held_capacity_shared_between_engines_but_raw_opportunities_uncapped(db):
    activate(db); cs=[candidate(t) for t in ('SPY','QQQ','IWM','AAPL')]; feed=Feed(cs)
    tick(db,feed,0,cs)
    tick(db,feed,1)
    assert position(db,ticker='AAPL').detail['reason']=='CAPACITY_SKIP'
    assert position(db,scenario='opportunity',ticker='AAPL').status=='OPEN'
    assert db.scalar(select(func.count()).select_from(RetestOpportunity))==4


def test_pending_invalidation_wins_over_available_later_quote(db):
    activate(db); feed=Feed(); tick(db,feed,0,feed.candidates); tick(db,feed,1)
    tick(db,feed,2,bar=candle(2,low=99,high=100.3))
    assert position(db,'treatment').status=='SKIPPED'
    assert position(db,'treatment').detail['reason']=='STOP_BEFORE_ENTRY'
    assert position(db).status=='UNPRICED'  # Touch overlaps actual entry minute: chronology unknown.


def test_restart_repeat_scan_and_same_quote_cannot_duplicate_cash(db):
    activate(db); feed=Feed(); tick(db,feed,0,feed.candidates)
    first=BASE+timedelta(minutes=1,seconds=5)
    tick(db,feed,1,quote_at=first)
    assert position(db).status=='PENDING_ENTRY'
    counts=db.scalar(select(func.count()).select_from(RetestEvent))
    db.expire_all()
    trial.process(db,feed,candidates=feed.candidates,evaluation_at=BASE+timedelta(minutes=1),
                  now=BASE+timedelta(minutes=2,seconds=6)); db.commit()
    assert db.scalar(select(func.count()).select_from(RetestEvent))==counts
    assert trial.balance(db,trial.account_key('control','base'))==(200000,0)


def test_transaction_rollback_and_retry_never_partially_funds_or_enters(db):
    trial.activate(db,revision='a'*40,now=ACTIVATION); db.rollback()
    assert db.get(RetestRun,trial.KEY) is None
    activate(db); feed=Feed()
    real_commit=db.commit
    db.commit=lambda:None
    tick(db,feed,0,feed.candidates)
    db.rollback(); db.commit=real_commit
    assert db.scalar(select(func.count()).select_from(RetestOpportunity))==0
    feed.bars=[];tick(db,feed,0,feed.candidates)
    assert db.scalar(select(func.count()).select_from(RetestOpportunity))==1


def test_closed_housekeeping_retains_unknown_exposure_and_cash(db):
    activate(db); feed=Feed(); tick(db,feed,0,feed.candidates);tick(db,feed,1)
    cash=trial.balance(db,trial.account_key('control','base'))
    trial.process(db,now=BASE.replace(hour=20));db.commit()
    assert position(db).status=='UNPRICED'
    assert trial.balance(db,trial.account_key('control','base'))==cash
    output=summary(db,now=BASE.replace(hour=20))
    assert output['verdict']=='INCONCLUSIVE'
    assert output['accounts'][0]['net_pnl_cents'] is None


def test_no_backfill_and_config_drift_disables_admission(db,monkeypatch):
    activate(db); feed=Feed(); tick(db,feed,0,feed.candidates)
    monkeypatch.setattr(trial,'configuration',lambda:{'changed':True})
    tick(db,feed,1,feed.candidates)
    assert position(db).status=='SKIPPED' and position(db).detail['reason']=='PROTOCOL_DRIFT'
    assert summary(db,now=feed.now)['protocol_drift']


def test_budget_reserve_unknown_budget_and_shared_refresh(db):
    activate(db); feed=Feed(); tick(db,feed,0,feed.candidates)
    feed.now=BASE
    assert trial.refresh_quotes(db,feed,now=BASE+timedelta(minutes=2))==1
    assert feed.calls==1  # six projections, one exact chain
    feed.remaining=30
    assert trial.refresh_quotes(db,feed,now=BASE+timedelta(minutes=2))==0
    feed.remaining=None
    assert trial.refresh_quotes(db,feed,now=BASE+timedelta(minutes=2))==0


def test_reads_are_nonmutating_and_opportunities_paginated(db):
    activate(db); feed=Feed();tick(db,feed,0,feed.candidates)
    before=[(m.__tablename__,db.scalar(select(func.count()).select_from(m))) for m in
        (RetestEvent,RetestPosition,RetestObservation,RetestOpportunity)]
    run=db.get(RetestRun,trial.KEY); revision=run.revision
    for _ in range(2):
        report=summary(db,view='opportunities',now=feed.now)
        assert report['pagination']['total']==2
    assert run.revision==revision
    assert before==[(m.__tablename__,db.scalar(select(func.count()).select_from(m))) for m in
        (RetestEvent,RetestPosition,RetestObservation,RetestOpportunity)]


def test_pre_activation_and_old_evaluation_never_import_candidates(db):
    activate(db); feed=Feed(); c=candidate()
    trial.process(db,feed,candidates=[c],evaluation_at=ACTIVATION-timedelta(minutes=1),now=BASE)
    db.commit()
    assert db.scalar(select(func.count()).select_from(RetestOpportunity))==0


def test_structured_entries_match_across_arms_and_do_not_use_retest(db):
    activate(db); c=candidate(mode='STRUCTURED_INTRADAY'); feed=Feed([c])
    tick(db,feed,0,[c]);tick(db,feed,1)
    control,treatment=position(db),position(db,'treatment')
    assert control.status==treatment.status=='OPEN'
    assert control.detail['entry_at']==treatment.detail['entry_at']
    assert control.detail['entry_debit_cents']==treatment.detail['entry_debit_cents']
    assert 'timing' not in treatment.detail


def test_unknown_exit_deadline_preserves_debit_and_slot(db):
    activate(db);feed=Feed();tick(db,feed,0,feed.candidates);tick(db,feed,1);tick(db,feed,2);tick(db,feed,3)
    tick(db,feed,4,bar=candle(4,low=100.2,high=103.1,close=102.9))
    cash=trial.balance(db,trial.account_key('control','base'))
    # No fresh post-request quote. The old quote cannot become an exit fill.
    old=feed.now
    for minute in (5,6,7,8):tick(db,feed,minute,quote_at=old)
    assert position(db).status=='UNPRICED'
    assert trial.balance(db,trial.account_key('control','base'))==cash
    assert not db.scalar(select(RetestEvent.id).where(RetestEvent.position_id==position(db).id,RetestEvent.kind=='EXIT'))


def test_zero_bid_is_real_exit_evidence_not_a_missing_quote(db):
    activate(db);feed=Feed();tick(db,feed,0,feed.candidates);tick(db,feed,1);tick(db,feed,2);tick(db,feed,3)
    tick(db,feed,4,bar=candle(4,low=100.2,high=103.1,close=102.9))
    feed.candidates=[c.model_copy(update={'contract':c.contract.model_copy(update={'bid':0,'ask':.01})}) for c in feed.candidates]
    tick(db,feed,5)
    assert position(db).status=='UNSETTLED' and position(db).detail['sale_cents']==0
    assert position(db).detail['net_pnl_cents']==-position(db).detail['entry_debit_cents']-50


def test_early_close_cancels_pending_entries_and_unknown_exposure_is_not_erased(db):
    activate(db)
    early=BASE.replace(month=11,day=27,hour=17,minute=43)
    c=candidate();q=c.contract.model_copy(update={'expiration':early.date(),'option_symbol':'SPY261127C00100000',
        'normalized_symbol':'SPY261127C00100000','timestamp':early,'bid_timestamp':early,'ask_timestamp':early,'received_at':early})
    c=c.model_copy(update={'contract':q,'generated_at':early+timedelta(minutes=1),
        'input_evidence':{'input_version':'current-session-v2','session_date':early.date().isoformat()}})
    feed=Feed([c]);feed.now=early+timedelta(minutes=1,seconds=5)
    bar=candle(0).model_copy(update={'timestamp':early});feed.bars=[bar]
    trial.process(db,feed,candidates=[c],evaluation_at=early,now=feed.now,
        capture={'SPY':{'planning_risk':2,'bars':[bar.model_dump(mode='json')]}});db.commit()
    p=position(db)
    plan=db.get(RetestOpportunity,p.opportunity_id).frozen
    assert plan['entry_cutoff']=='2026-11-27T17:45:00+00:00'
    feed.now=early+timedelta(minutes=2,seconds=5)
    trial.process(db,feed,evaluation_at=early+timedelta(minutes=1),now=feed.now);db.commit()
    assert position(db).status=='SKIPPED' and position(db).detail['reason']=='SESSION_CUTOFF'


def test_cancelled_opportunity_still_records_missed_underlying_target(db):
    activate(db);feed=Feed();tick(db,feed,0,feed.candidates)
    # No touch back to B for five bars; treatment times out but path logging continues.
    for minute in range(1,6):tick(db,feed,minute,bar=candle(minute,low=100.1))
    raw=position(db,'treatment','opportunity')
    assert raw.status=='SKIPPED' and raw.detail['reason']=='FIVE_BAR_EXPIRY'
    tick(db,feed,6,bar=candle(6,low=100.2,high=103.1,close=102.9))
    assert raw.detail['opportunity_outcome']['reason']=='TARGET'
    assert 'net_pnl_cents' not in raw.detail


def test_missing_exit_valuation_is_unknown_on_read_not_zero(db):
    activate(db);feed=Feed();tick(db,feed,0,feed.candidates);tick(db,feed,1)
    db.expire_all()
    p=position(db);p.detail={k:v for k,v in p.detail.items() if k!='valuation'};db.commit()
    trial.process(db,now=BASE.replace(hour=20));db.commit()
    result=summary(db,now=BASE.replace(hour=20))
    assert result['latest']['accounts'][trial.account_key('control','base')]['equity_cents'] is None


def test_mid_session_restart_waits_for_real_candles_instead_of_inventing_gap(db):
    activate(db);feed=Feed();tick(db,feed,0,feed.candidates);tick(db,feed,1)
    before=db.scalar(select(func.count()).select_from(RetestObservation))
    trial.process(db,now=BASE+timedelta(minutes=3));db.commit()
    assert position(db).status=='OPEN' and position(db,'treatment').status=='PENDING_ENTRY'
    assert db.scalar(select(func.count()).select_from(RetestObservation))==before


def test_early_close_timed_exit_waits_for_later_quote_in_both_arms(db):
    activate(db)
    early=BASE.replace(month=11,day=27,hour=17,minute=40)
    c=candidate();q=c.contract.model_copy(update={'expiration':early.date(),'option_symbol':'SPY261127C00100000',
        'normalized_symbol':'SPY261127C00100000'})
    c=c.model_copy(update={'contract':q,'generated_at':early+timedelta(minutes=1),
        'input_evidence':{'input_version':'current-session-v2','session_date':early.date().isoformat()}})
    feed=Feed([c])
    for minute in range(7):
        at=early+timedelta(minutes=minute)
        feed.now=at+timedelta(minutes=1,seconds=5)
        feed.bars.append(candle(minute,low=99.9 if minute==1 else 100.1).model_copy(update={'timestamp':at}))
        trial.process(db,feed,candidates=[c] if minute==0 else (),evaluation_at=at,now=feed.now,
            capture={'SPY':{'planning_risk':2,'bars':[b.model_dump(mode='json') for b in feed.bars]}})
        db.commit()
        if minute==5:
            for arm in trial.ARMS:
                assert position(db,arm).status=='EXIT_PENDING'
                assert position(db,arm).detail['exit_reason']=='TIMED_EXIT'
    for arm in trial.ARMS:
        assert position(db,arm).status=='UNSETTLED'
        assert position(db,arm).detail['exit_at']==feed.now.isoformat()


def test_research_failure_rolls_back_its_events_but_preserves_baseline_scan(db,monkeypatch):
    from app.services import signal_engine
    from app.db.models import SignalScan
    from app.schemas.market import ProviderStatus
    activate(db)
    feed=Feed()
    monkeypatch.setattr(feed,'status',lambda:ProviderStatus(provider='tastytrade',mode='live',status='healthy',
        delay_seconds=0,latest_timestamp=BASE,message='Synthetic feed'))
    monkeypatch.setattr(signal_engine,'rank_parlays',lambda *a,**kw:[])
    monkeypatch.setattr(signal_engine,'rank_structured_intraday',lambda *a,**kw:[])
    for name in ('track_candidates','track_lottery_scan','record_option_observations',
                 'refresh_account_quotes','advance_account','advance_lotto_trials','_position_alerts','_performance_alerts'):
        monkeypatch.setattr(signal_engine,name,lambda *a,**kw:None)
    monkeypatch.setattr(trial,'refresh_quotes',lambda *a,**kw:0)
    def fail(session,*args,**kwargs):
        trial.event(session,'should-rollback',BASE,'SYNTHETIC_FAILED_WRITE')
        raise ValueError('Synthetic research failure')
    monkeypatch.setattr(trial,'process',fail)
    result=signal_engine.run_signal_scan(db,feed,['SPY'],evaluation_at=BASE)
    assert result is not None and db.get(SignalScan,result.id) is not None
    assert db.scalar(select(func.count()).select_from(RetestEvent).where(RetestEvent.kind=='SYNTHETIC_FAILED_WRITE'))==0
    assert db.scalar(select(func.count()).select_from(RetestEvent).where(RetestEvent.kind=='COLLECTION_ERROR'))==1
