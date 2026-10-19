from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.models import LotteryQuoteSnapshot, LotteryTracker, LottoTrialAccount, LottoTrialEvent, LottoTrialPosition
from app.db.session import Base
from app.services.lotto_trials import (TRIAL_START, advance_lotto_trials, balance, ensure_lotto_trials,
                                      fresh_point, key_for, lotto_trial_summary)
from app.services.lottery_tracker import path_evidence

NOW = datetime(2026, 10, 19, 14, 0, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def tracker(db, name='SPY', *, now=NOW, right='call', score=90, provider='tastytrade'):
    row = LotteryTracker(id=name+right, trading_date=now.date(), symbol=name,
        option_symbol=name+right, expiration=now.date(), right=right, strike=100,
        first_seen_at=now, last_qualified_at=now, entry_ask=.20, entry_bid=.18,
        entry_underlying_price=100, setup_score=score, initial_snapshot={'input_evidence':{
            'input_version':'current-session-v2', 'session_date':now.date().isoformat(),
            'lottery_version':f'lotto-{right}-session-v2'}}, provider=provider, data_mode='live',
        verification_status='verified', verification_reason='fixture', actionable=True,
        created_at=now, updated_at=now)
    db.add(row)
    db.flush()
    return row


def quote(db, row, now, bid=.18, ask=.20, **changes):
    values = dict(tracker_id=row.id, received_at=now, observed_at=now, quote_timestamp=now,
        bid_timestamp=now, ask_timestamp=now, provider='tastytrade', data_mode='live', bid=bid,
        ask=ask, midpoint=(bid+ask)/2, last=bid, spread_percent=10, volume=1500, open_interest=2000)
    values.update(changes)
    q = LotteryQuoteSnapshot(**values)
    db.add(q)
    db.flush()
    return q


def position(db, rule='fixed5', right='call', tracker_id=None):
    stmt = select(LottoTrialPosition).where(LottoTrialPosition.account_key == key_for(right, rule))
    if tracker_id:
        stmt = stmt.where(LottoTrialPosition.tracker_id == tracker_id)
    return db.scalar(stmt)


def entered(db, right='call'):
    ensure_lotto_trials(db, TRIAL_START)
    row = tracker(db, right=right)
    quote(db, row, NOW)
    advance_lotto_trials(db, now=NOW)
    assert position(db, right=right).status == 'PENDING_ENTRY'
    quote(db, row, NOW+timedelta(minutes=1))
    advance_lotto_trials(db, now=NOW+timedelta(minutes=1))
    return row


def test_scheduled_read_is_read_only_and_funding_idempotent(db):
    assert lotto_trial_summary(db, now=TRIAL_START-timedelta(seconds=1))['status'] == 'SCHEDULED'
    assert lotto_trial_summary(db, now=NOW)['status'] == 'NOT_STARTED'
    assert db.scalar(select(func.count()).select_from(LottoTrialAccount)) == 0
    ensure_lotto_trials(db, TRIAL_START)
    advance_lotto_trials(db, now=TRIAL_START)
    advance_lotto_trials(db, now=TRIAL_START)
    assert db.scalar(select(func.count()).select_from(LottoTrialAccount)) == 4
    assert db.scalar(select(func.count()).select_from(LottoTrialEvent).where(LottoTrialEvent.kind == 'FUNDING')) == 4
    assert balance(db, key_for('call','fixed5')) == (50000,0,0)
    assert balance(db, key_for('put','trail40')) == (50000,0,0)
    with pytest.raises(ValueError):
        lotto_trial_summary(db, 'bogus')


def test_pair_uses_later_quote_costs_one_idea_and_persists_restart(db):
    ensure_lotto_trials(db, TRIAL_START)
    chosen = tracker(db, score=99)
    tracker(db, 'QQQ', score=80)
    # Old provider history is not imported.
    tracker(db, 'OLD', now=TRIAL_START-timedelta(days=1))
    quote(db, chosen, NOW)
    advance_lotto_trials(db, now=NOW)
    assert position(db, tracker_id=chosen.id).status == 'PENDING_ENTRY'
    assert position(db, tracker_id='QQQcall').status == 'SKIPPED'
    assert db.scalar(select(func.count()).select_from(LottoTrialPosition)) == 4
    quote(db, chosen, NOW+timedelta(minutes=1))
    advance_lotto_trials(db, now=NOW+timedelta(minutes=1))
    for rule in ('fixed5','trail40'):
        p = position(db, rule, tracker_id=chosen.id)
        assert p.detail['entry_debit_cents'] == 2250  # $20 ask + $1 slip + $1.50 costs
        assert p.status == 'OPEN'
        assert balance(db, key_for('call',rule)) == (47750,0,0)
    db.commit()
    count = db.scalar(select(func.count()).select_from(LottoTrialEvent))
    db.expire_all()
    advance_lotto_trials(db, now=NOW+timedelta(minutes=1))
    assert db.scalar(select(func.count()).select_from(LottoTrialEvent)) == count
    assert lotto_trial_summary(db, now=NOW+timedelta(minutes=1))['equity_cents'] == 49400


@pytest.mark.parametrize('changes',[
    {'provider':'tradier'}, {'data_mode':'delayed'}, {'received_at':None},
    {'bid_timestamp':NOW-timedelta(minutes=2)}, {'ask_timestamp':NOW+timedelta(seconds=1)},
    {'bid':.25}, {'bid':float('inf')}, {'bid_timestamp':None},
])
def test_quote_rejects_wrong_provider_missing_stale_future_crossed(db, changes):
    row = tracker(db)
    quote(db, row, NOW, **changes)
    assert fresh_point(db, row.id, NOW) is None


def test_recovery_never_enters_old_discovery_and_deadline_cannot_fill(db):
    ensure_lotto_trials(db, TRIAL_START)
    old = tracker(db)
    advance_lotto_trials(db, now=NOW+timedelta(minutes=3))
    assert position(db).status == 'SKIPPED'
    assert 'too old' in position(db).detail['reason']
    new = tracker(db, 'QQQ', now=NOW+timedelta(minutes=4))
    advance_lotto_trials(db, now=NOW+timedelta(minutes=4))
    quote(db, new, NOW+timedelta(minutes=7))
    advance_lotto_trials(db, now=NOW+timedelta(minutes=7))
    assert position(db, tracker_id=new.id).status == 'SKIPPED'
    assert balance(db, key_for('call','fixed5')) == (50000,0,0)
    assert old.entry_ask == .20


def test_fixed_target_is_decision_then_later_bid_not_perfect_fill_and_settles(db):
    row = entered(db)
    quote(db, row, NOW+timedelta(minutes=2), 1.10, 1.12)
    advance_lotto_trials(db, now=NOW+timedelta(minutes=2))
    assert position(db).status == 'OPEN'
    assert position(db).detail['exit_reason'] == '5X_TRIGGER'
    quote(db, row, NOW+timedelta(minutes=3), .80, .82)
    advance_lotto_trials(db, now=NOW+timedelta(minutes=3))
    p = position(db)
    assert p.status == 'UNSETTLED'
    assert p.detail['sale_cents'] == 7900
    assert p.detail['net_proceeds_cents'] == 7850
    assert p.detail['net_pnl_cents'] == 5600
    assert balance(db, key_for('call','fixed5')) == (47700,7900,5600)
    assert lotto_trial_summary(db, now=NOW+timedelta(minutes=3))['equity_cents'] == 55600
    due = datetime.fromisoformat(p.detail['settles_at'])
    advance_lotto_trials(db, now=due)
    assert balance(db, key_for('call','fixed5')) == (55600,0,5600)
    assert position(db).status == 'CLOSED'


def test_trail_waits_for_2x_then_40_percent_drop_then_later_quote(db):
    row = entered(db, right='put')
    for minute,bid in [(2,.30),(3,.15),(4,.50),(5,.60),(6,.35),(7,.28)]:
        quote(db, row, NOW+timedelta(minutes=minute), bid, bid+.02)
        advance_lotto_trials(db, now=NOW+timedelta(minutes=minute))
        p = position(db, 'trail40', 'put')
        if minute<6:
            assert 'exit_requested_at' not in p.detail
        if minute==6:
            assert p.status == 'OPEN' and p.detail['exit_reason'] == '40_PERCENT_TRAIL'
    assert p.status == 'UNSETTLED'
    assert p.detail['sale_cents'] == 2700
    assert position(db, 'fixed5', 'put').status == 'OPEN'
    assert balance(db, key_for('call','fixed5')) == (50000,0,0)


def test_unknown_stale_and_end_of_day_do_not_invent_zero_or_free_capital(db):
    entered(db)
    summary = lotto_trial_summary(db, now=NOW+timedelta(minutes=3))
    assert summary['equity_cents'] is None and summary['unpriced_positions'] == 1
    advance_lotto_trials(db, now=NOW.replace(hour=19,minute=55))
    assert position(db).detail['exit_reason'] == 'SESSION_END'
    advance_lotto_trials(db, now=NOW.replace(hour=20))
    assert position(db).status == 'UNPRICED'
    assert balance(db, key_for('call','fixed5')) == (47750,0,0)
    next_day = NOW+timedelta(days=1)
    tracker(db, 'QQQ', now=next_day)
    advance_lotto_trials(db, now=next_day)
    assert position(db, tracker_id='QQQcall').status == 'SKIPPED'
    assert lotto_trial_summary(db, now=next_day)['equity_cents'] is None


def test_path_evidence_counts_distinct_quotes_not_repeats_or_missing_minutes(db):
    row = tracker(db)
    points = [quote(db,row,NOW+timedelta(minutes=i),bid,bid+.02) for i,bid in enumerate([.1,.4,.5,.2,1.0])]
    points.append(quote(db,row,NOW+timedelta(minutes=7),1.1,1.2))
    points.append(quote(db,row,NOW+timedelta(minutes=8),1.1,1.2,bid_timestamp=NOW+timedelta(minutes=7)))
    data = path_evidence(.20, points, NOW)
    assert data['thresholds'][0]['distinct_quotes'] == 4
    assert data['thresholds'][0]['longest_observed_span_seconds'] == 60
    assert data['thresholds'][0]['lowest_before_hit_percent'] == -50
    assert data['thresholds'][1]['minutes_to_first'] == 4
    assert data['thresholds'][1]['longest_observed_span_seconds'] == 0


@pytest.mark.parametrize('constraint', ['entry_cap','cash','daily_cap','ticker_day'])
def test_common_entry_budget_controls_cannot_diverge_between_variants(db, constraint):
    from app.services.lotto_trials import event
    ensure_lotto_trials(db, TRIAL_START)
    for rule in ('fixed5','trail40'):
        key = key_for('call',rule)
        if constraint == 'cash':
            event(db,key,'TEST_PRIOR_DEBIT','test:debit',NOW,settled=-49000)
        if constraint in ('daily_cap','ticker_day'):
            for i in range(2 if constraint == 'daily_cap' else 1):
                db.add(LottoTrialPosition(account_key=key,tracker_id=f'prior{i}',status='CLOSED',
                    detail={'entry_debit_cents':4500,'symbol':'SPY' if constraint=='ticker_day' else f'OTHER{i}',
                            'date':NOW.date().isoformat()}))
    db.flush()
    row = tracker(db)
    advance_lotto_trials(db, now=NOW)
    bid,ask = (.48,.49) if constraint=='entry_cap' else (.18,.20)
    quote(db,row,NOW+timedelta(minutes=1),bid,ask)
    advance_lotto_trials(db, now=NOW+timedelta(minutes=1))
    for rule in ('fixed5','trail40'):
        assert position(db,rule,tracker_id=row.id).status == 'SKIPPED'
    assert db.scalar(select(func.count()).select_from(LottoTrialEvent).where(LottoTrialEvent.kind=='ENTRY')) == 0


def test_expired_exit_deadline_stays_unknown_even_if_later_quote_is_profitable(db):
    row = entered(db)
    quote(db,row,NOW+timedelta(minutes=2),1.10,1.12)
    advance_lotto_trials(db, now=NOW+timedelta(minutes=2))
    quote(db,row,NOW+timedelta(minutes=6),2.0,2.1)
    advance_lotto_trials(db, now=NOW+timedelta(minutes=6))
    assert position(db).status == 'UNPRICED'
    assert 'sale_cents' not in position(db).detail


def test_verified_zero_bid_is_not_confused_with_missing_quote(db):
    row = entered(db)
    quote(db,row,NOW+timedelta(minutes=2),1.10,1.12)
    advance_lotto_trials(db, now=NOW+timedelta(minutes=2))
    quote(db,row,NOW+timedelta(minutes=3),0,.02)
    advance_lotto_trials(db, now=NOW+timedelta(minutes=3))
    assert position(db).status == 'UNSETTLED'
    assert position(db).detail['sale_cents'] == 0
    assert position(db).detail['net_pnl_cents'] == -2300
    assert lotto_trial_summary(db,now=NOW+timedelta(minutes=3))['equity_cents'] == 47700


def test_early_close_entry_and_exit_windows_follow_exchange_calendar(db):
    day = datetime(2026,11,27,17,0,tzinfo=timezone.utc)  # Noon ET; close 13:00.
    ensure_lotto_trials(db, day-timedelta(minutes=1))
    row = tracker(db, now=day)
    advance_lotto_trials(db,now=day)
    quote(db,row,day+timedelta(minutes=1))
    advance_lotto_trials(db,now=day+timedelta(minutes=1))
    late = tracker(db,'QQQ',now=day+timedelta(minutes=45),right='put')
    advance_lotto_trials(db,now=day+timedelta(minutes=45))
    assert 'final 15 minutes' in position(db,right='put',tracker_id=late.id).detail['reason']
    advance_lotto_trials(db,now=day+timedelta(minutes=55))
    assert position(db).detail['exit_reason'] == 'SESSION_END'
    advance_lotto_trials(db,now=day+timedelta(hours=1))
    assert position(db).status == 'UNPRICED'


def test_put_experiment_never_changes_call_archive_totals(db):
    from app.api.routes import lottery_trackers
    tracker(db)
    tracker(db,right='put')
    listing = lottery_trackers(trading_date=NOW.date(),db=db)
    assert listing.summary.contract_count == 1
    assert [row.right for row in listing.trackers] == ['call']
    assert db.scalar(select(func.count()).select_from(LotteryTracker)) == 2


def test_summary_pagination_and_marks_are_read_only_and_use_eastern_date(db):
    ensure_lotto_trials(db,TRIAL_START)
    for i in range(14):
        tracker(db,f'TEST{i}')
    advance_lotto_trials(db,now=NOW)
    # 01:00 UTC is still the prior exchange date; do not create a second daily bucket.
    advance_lotto_trials(db,now=NOW.replace(hour=1)+timedelta(days=1))
    before = db.scalar(select(func.count()).select_from(LottoTrialEvent))
    first = lotto_trial_summary(db,page=1,now=NOW)
    second = lotto_trial_summary(db,page=2,now=NOW)
    assert len(first['trades']) == 12 and len(second['trades']) == 2
    assert first['pagination']['total'] == 14
    assert len(first['equity_history']['daily']) == 1
    assert first['equity_history']['daily'][0]['date'] == '2026-10-19'
    assert db.scalar(select(func.count()).select_from(LottoTrialEvent)) == before
