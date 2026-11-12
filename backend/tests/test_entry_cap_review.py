from datetime import timedelta
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.db.models import EntryCapReviewEvent, ForwardPaperAccount, ForwardPaperEvent, ForwardPaperPosition
from app.services import entry_cap_review as review, expanded_account as main, forward_account as baseline
from app.services.retest_trials import code_hash
from test_forward_account import Quotes, START, candidate
from test_performance import database


@pytest.fixture
def db(monkeypatch):
    activate_at=START.replace(hour=12)
    monkeypatch.setattr(baseline,'TRIAL_START',activate_at-timedelta(days=1))
    monkeypatch.setattr(main,'get_settings',lambda:SimpleNamespace(paper_only=True,market_data_provider='tastytrade'))
    with database()() as session:
        baseline.ensure_account(session,activate_at)
        main.activate(session,revision='a'*40,now=activate_at)
        session.commit()
        yield session


def skip(db, *, ask=1.0, name='first', ticker='SPY', now=START):
    trade=candidate(db,name=name,ticker=ticker,now=now)
    identity={'symbol':ticker,'option_symbol':f'{ticker}260803C00100000','normalized_symbol':f'{ticker}260803C00100000'}
    main.advance_account(db,Quotes(now,ask=ask,bid=ask-.02,**identity),now=now)
    at=now+timedelta(seconds=2)
    main.advance_account(db,Quotes(at,ask=ask,bid=ask-.02,**identity),now=at)
    return trade,db.scalar(select(ForwardPaperPosition).where(ForwardPaperPosition.account_key==main.KEY,
        ForwardPaperPosition.signal_id==trade.signal_id))


def request_exit(db,trade):
    trade.strategy_snapshot={**trade.strategy_snapshot,'result_model':{'version':'post-confirmation-quote-v1'}}
    trade.exit_at=START+timedelta(minutes=10)
    trade.exit_reason='TARGET';trade.result_r=1.5
    db.flush()
    at=trade.exit_at+timedelta(seconds=10)
    review.advance(db,Quotes(at,bid=.34,ask=.44),now=at)
    return at


def counts(db):
    return {m.__name__:db.scalar(select(func.count()).select_from(m)) for m in
            (ForwardPaperAccount,ForwardPaperPosition,ForwardPaperEvent,EntryCapReviewEvent)}


def test_budget_skip_saves_real_decision_quote_without_funding_or_rule_change(db):
    policy=json.dumps(db.get(ForwardPaperAccount,main.KEY).policy,sort_keys=True)
    _,p=skip(db)
    e=db.scalar(select(EntryCapReviewEvent).where(EntryCapReviewEvent.kind=='ENTRY'))
    assert p.status=='SKIPPED' and p.detail['reason']==review.REASON
    assert e.detail['entry_quote']['ask']==1.0
    assert e.detail['entry_quote']['receipt_basis']=='REST_RESPONSE_RECEIVED_V1'
    assert e.detail['entry_debit_cents']==10250 and e.detail['all_in_cents']==10300
    assert e.detail['cap_only'] is True
    assert main._balance(db)==(200000,0)
    assert json.dumps(db.get(ForwardPaperAccount,main.KEY).policy,sort_keys=True)==policy
    assert db.scalar(select(func.count()).select_from(ForwardPaperEvent).where(
        ForwardPaperEvent.account_key==main.KEY,ForwardPaperEvent.kind=='ENTRY'))==0


def test_later_exit_has_signed_net_loss_and_does_not_change_real_trade(db):
    trade,p=skip(db);at=request_exit(db,trade)
    assert db.scalar(select(func.count()).select_from(EntryCapReviewEvent).where(EntryCapReviewEvent.kind=='EXIT'))==0
    later=at+timedelta(seconds=2)
    main_cash_before=counts(db)['ForwardPaperEvent']
    review.advance(db,Quotes(later,bid=.34,ask=.44),now=later)
    data=review.summary(db)
    assert data['comparisons'][0]['negative']==1
    assert data['comparisons'][0]['average_net_cents']==-7000
    assert data['rows'][0]['net_pnl_cents']==-7000
    assert data['rows'][0]['status']=='PRICED'
    assert p.status=='SKIPPED' and trade.result_r==1.5
    assert counts(db)['ForwardPaperEvent']==main_cash_before
    assert main._balance(db)==(200000,0)


def test_positive_opportunity_is_reported_with_costs(db):
    trade,_=skip(db);at=request_exit(db,trade)+timedelta(seconds=2)
    review.advance(db,Quotes(at,bid=1.60,ask=1.62),now=at)
    result=review.summary(db)['comparisons'][0]
    assert result['positive']==1 and result['average_net_cents']==5600


@pytest.mark.parametrize('ask,expected',[(1.0,[1,1]),(1.3,[0,1]),(1.6,[0,0])])
def test_comparison_caps_are_filters_and_never_account_settings(db,ask,expected):
    skip(db,ask=ask)
    assert [c['eligible'] for c in review.summary(db)['comparisons']]==expected
    assert db.get(ForwardPaperAccount,main.KEY).policy['max_entry_cents']==10000


def test_price_skip_that_also_lacks_cash_is_not_cap_only(db):
    db.add(ForwardPaperEvent(account_key=main.KEY,event_key='test-spent',occurred_at=START,
        kind='TEST',settled_cents=-199000,unsettled_cents=0,realized_cents=0,fee_cents=0,detail={}))
    db.flush();skip(db)
    result=review.summary(db)
    assert result['cap_only_records']==0
    assert [c['eligible'] for c in result['comparisons']]==[0,0]
    assert result['rows'][0]['cap_only'] is False


@pytest.mark.parametrize('changes',[
    {'received_at':None}, {'receipt_basis':'UNKNOWN'},
    {'received_at':START}, {'bid_timestamp':START}, {'ask_timestamp':START},
    {'received_at':START+timedelta(seconds=20)}, {'option_symbol':'SPY260803C00101000'},
])
def test_missing_stale_repeated_future_or_wrong_contract_quote_never_prices_exit(db,changes):
    trade,_=skip(db);at=request_exit(db,trade)+timedelta(seconds=2)
    review.advance(db,Quotes(at,bid=.34,ask=.44,**changes),now=at)
    assert review.summary(db)['comparisons'][0]['priced']==0


def test_expired_exit_window_stays_unknown_despite_later_good_quote(db):
    trade,_=skip(db);requested=request_exit(db,trade)
    late=requested+timedelta(seconds=181)
    review.advance(db,Quotes(late,bid=5,ask=5.1),now=late)
    review.advance(db,Quotes(late+timedelta(minutes=1),bid=6,ask=6.1),now=late+timedelta(minutes=1))
    data=review.summary(db)
    assert data['comparisons'][0]['gaps']==1 and data['comparisons'][0]['priced']==0
    assert data['comparisons'][0]['average_net_cents'] is None
    assert data['rows'][0]['net_pnl_cents'] is None


def test_restart_does_not_duplicate_evidence_or_reprice_a_closed_example(db):
    trade,_=skip(db);at=request_exit(db,trade)+timedelta(seconds=2)
    provider=Quotes(at,bid=.34,ask=.44)
    review.advance(db,provider,now=at);db.commit();before=counts(db)
    review.advance(db,provider,now=at)
    review.advance(db,Quotes(at+timedelta(minutes=1),bid=9,ask=9.1),now=at+timedelta(minutes=1))
    assert counts(db)==before
    assert review.summary(db)['rows'][0]['net_pnl_cents']==-7000


@pytest.mark.parametrize('gap', ['DATA_GAP','SESSION_END','MISSED_DECISION'])
def test_missing_underlying_or_session_boundary_is_not_a_zero_sale(db,gap):
    trade,_=skip(db)
    at=START+timedelta(minutes=10)
    if gap=='DATA_GAP':trade.exit_reason='DATA_GAP'
    elif gap=='SESSION_END':at=START.replace(hour=20,minute=0)
    else:
        trade.exit_at=START+timedelta(minutes=1);trade.exit_reason='STOP'
        at=START+timedelta(minutes=8)
    db.flush();review.advance(db,Quotes(at,bid=1,ask=1.02),now=at)
    result=review.summary(db)['comparisons'][0]
    assert result['gaps']==1 and result['average_net_cents'] is None


def test_optional_failure_cannot_undo_original_skip(db,monkeypatch):
    monkeypatch.setattr(review,'_event',lambda *_args,**_kw:(_ for _ in ()).throw(RuntimeError('audit failed')))
    _,position=skip(db)
    db.commit()
    assert position.status=='SKIPPED'
    assert main._balance(db)==(200000,0)
    assert counts(db)['EntryCapReviewEvent']==0


def test_legacy_skip_is_counted_without_reconstruction_and_reads_are_nonmutating(db):
    _,p=skip(db)
    db.query(EntryCapReviewEvent).delete();db.flush()  # Emulate an existing pre-instrumentation skip.
    before=counts(db)
    from app.api.routes import entry_cap_review
    result=entry_cap_review(page=1,db=db)
    assert result['legacy_without_entry_receipt']==1 and result['recorded_skips']==0
    assert entry_cap_review(page=1,db=db)==result
    review.advance(db,Quotes(START+timedelta(minutes=1),bid=2,ask=2.1),now=START+timedelta(minutes=1))
    assert counts(db)==before and p.status=='SKIPPED'


def test_collection_never_requests_data_and_existing_study_hash_is_unchanged(db):
    trade,_=skip(db);at=request_exit(db,trade)+timedelta(seconds=2)
    class CacheOnly(Quotes):
        def option_chain(self,*_):raise AssertionError('No provider request allowed')
    review.advance(db,CacheOnly(at,bid=.34,ask=.44),now=at)
    assert review.summary(db)['collection']=='CACHE_ONLY_NO_ADDITIONAL_REQUESTS'
    assert code_hash()=='4fe8e0a500a9d2440e6e0de0bb93bcd46f7c006abf78710618298318ec14cc57'


def test_open_or_missing_outcome_stays_in_denominator(db):
    trade,_=skip(db)
    skip(db,name='second',ticker='QQQ',now=START+timedelta(seconds=3))
    at=request_exit(db,trade)+timedelta(seconds=2)
    review.advance(db,Quotes(at,bid=.34,ask=.44),now=at)
    result=review.summary(db)['comparisons'][0]
    assert result['eligible']==2 and result['priced']==1 and result['pending']==1
    assert result['average_net_cents']==-7000
    assert result['complete_quote_evidence'] is False


def test_empty_read_never_creates_accounts_or_quotes():
    with database()() as db:
        before=counts(db);data=review.summary(db)
        assert data['current_cap_cents'] is None and data['recorded_skips']==0
        assert counts(db)==before
