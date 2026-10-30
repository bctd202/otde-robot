from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import func, select

from app.db.models import ForwardPaperEvent, ForwardPaperPosition
from app.services import expanded_account as expanded
import test_expanded_account as fixtures
from test_expanded_account import activate, discover, fill, AllQuotes
from test_forward_account import START
from test_forward_account import candidate

db = fixtures.db


def test_spy_timeline_uses_full_post_decision_deadline_without_same_scan_fill(db):
    activate(db); trades=discover(db); fill(db)
    trade=trades[0]; trade.exit_reason='STOP'; trade.exit_at=START+timedelta(minutes=10)
    requested=trade.exit_at+timedelta(seconds=69)
    expanded.advance_account(db,AllQuotes(requested),now=requested)
    position=db.scalar(select(ForwardPaperPosition))
    assert position.status=='OPEN' and position.detail['exit_requested_at']==requested.isoformat()
    # First later scan has no valid quote. The second is 188 seconds after
    # candle start, still only 119 seconds after the actual decision.
    expanded.advance_account(db,None,now=requested+timedelta(seconds=60))
    later=trade.exit_at+timedelta(seconds=188)
    expanded.advance_account(db,AllQuotes(later,bid=.30,ask=.32),now=later)
    assert position.status=='UNSETTLED'
    assert position.detail['exit_quote']['received_at']==later.isoformat()
    assert position.detail['execution_version']=='decision-clock-v2'


def test_degraded_candles_do_not_block_independently_verified_exit_but_still_block_entry(db):
    class Feed(AllQuotes):
        def status(self): return SimpleNamespace(status='degraded',mode='live')
        def option_execution_status(self):return SimpleNamespace(status='healthy',mode='live')
    activate(db);trades=discover(db);fill(db)
    trade=trades[0];trade.exit_reason='TARGET';trade.exit_at=START+timedelta(minutes=1)
    requested=trade.exit_at+timedelta(minutes=1)
    candidate(db,'second','SECOND',now=requested)
    expanded.advance_account(db,Feed(requested),now=requested)
    later=requested+timedelta(seconds=2)
    expanded.advance_account(db,Feed(later),now=later)
    assert db.scalar(select(ForwardPaperPosition)).status=='UNSETTLED'
    assert db.scalar(select(ForwardPaperPosition).where(ForwardPaperPosition.signal_id=='second')).status=='PENDING_ENTRY'


def test_request_deadline_does_not_extend_and_legacy_unknowns_are_not_repaired(db):
    activate(db); trades=discover(db);fill(db)
    trade=trades[0];trade.exit_reason='STOP';trade.exit_at=START+timedelta(minutes=1)
    requested=trade.exit_at+timedelta(minutes=1)
    expanded.advance_account(db,None,now=requested)
    late=requested+timedelta(seconds=181)
    expanded.advance_account(db,AllQuotes(late),now=late)
    p=db.scalar(select(ForwardPaperPosition))
    assert p.status=='UNPRICED'
    original=dict(p.detail)
    expanded.advance_account(db,AllQuotes(late+timedelta(seconds=1)),now=late+timedelta(seconds=1))
    assert p.status=='UNPRICED' and p.detail==original


def test_boundary_is_one_append_only_event_and_does_not_refund_account(db):
    activate(db); discover(db); at=fill(db)
    expanded.advance_account(db,AllQuotes(at),now=at)
    assert db.scalar(select(func.count()).select_from(ForwardPaperEvent).where(
        ForwardPaperEvent.account_key==expanded.KEY,ForwardPaperEvent.kind=='EXECUTION_BOUNDARY'))==1
    assert db.scalar(select(func.count()).select_from(ForwardPaperEvent).where(
        ForwardPaperEvent.account_key==expanded.KEY,ForwardPaperEvent.kind=='FUNDING'))==1
    assert expanded._balance(db)==(195250,0)


def test_pre_repair_position_keeps_legacy_deadline(db):
    activate(db); trades=discover(db); fill(db)
    p=db.scalar(select(ForwardPaperPosition))
    p.detail={k:v for k,v in p.detail.items() if k!='execution_version'}
    trades[0].exit_reason='STOP';trades[0].exit_at=START+timedelta(minutes=10)
    requested=trades[0].exit_at+timedelta(seconds=69)
    expanded.advance_account(db,None,now=requested)
    later=trades[0].exit_at+timedelta(seconds=188)
    expanded.advance_account(db,AllQuotes(later),now=later)
    assert p.status=='UNPRICED'
