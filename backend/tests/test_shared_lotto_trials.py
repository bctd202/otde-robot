"""Shared cash trials must never double capital or rewrite directional history."""
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.models import LottoTrialAccount, LottoTrialEvent, LottoTrialPosition
from app.db.session import Base
from app.services.lotto_trials import (SHARED_TRIAL_START, advance_lotto_trials, balance,
    ensure_lotto_trials, event, key_for, lotto_trial_summary)
from tests.test_lotto_trials import position, quote, tracker

NOW = SHARED_TRIAL_START + timedelta(minutes=30)


@pytest.fixture
def db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def shared_position(db, rule='fixed5', tracker_id=None):
    return position(db, rule, 'both', tracker_id)


def enter(db, *, right='call'):
    ensure_lotto_trials(db, SHARED_TRIAL_START)
    row = tracker(db, now=NOW, right=right)
    advance_lotto_trials(db, now=NOW)
    quote(db, row, NOW+timedelta(minutes=1))
    advance_lotto_trials(db, now=NOW+timedelta(minutes=1))
    return row


def test_new_default_is_scheduled_read_only_then_once_funded_without_history(db):
    before = SHARED_TRIAL_START-timedelta(days=1)
    ensure_lotto_trials(db, before)
    old_accounts = [(a.key, a.policy, a.activated_at) for a in db.scalars(select(LottoTrialAccount))]
    old_events = [(e.id, e.account_key, e.detail) for e in db.scalars(select(LottoTrialEvent))]
    old = tracker(db, now=SHARED_TRIAL_START)
    response = lotto_trial_summary(db, now=before)
    assert response['status'] == 'SCHEDULED'
    assert response['account_key'] == key_for('both', 'fixed5')
    assert [a['scope'] for a in response['accounts']] == ['combined']*2+['directional']*4
    assert db.scalar(select(func.count()).select_from(LottoTrialAccount)) == 4
    # Late deployment starts at the real activation time, not Monday's open.
    ensure_lotto_trials(db, NOW)
    ensure_lotto_trials(db, NOW+timedelta(seconds=1))
    assert db.scalar(select(func.count()).select_from(LottoTrialAccount)) == 6
    for key, policy, activated_at in old_accounts:
        account = db.get(LottoTrialAccount, key)
        assert account.policy == policy and account.activated_at == activated_at
    assert [(e.id, e.account_key, e.detail) for e in db.scalars(select(LottoTrialEvent).where(
        LottoTrialEvent.id <= len(old_events)))] == old_events
    for rule in ('fixed5', 'trail40'):
        key = key_for('both', rule)
        assert balance(db, key) == (50000, 0, 0)
        assert db.scalar(select(func.count()).select_from(LottoTrialEvent).where(
            LottoTrialEvent.account_key == key, LottoTrialEvent.kind == 'FUNDING')) == 1
    advance_lotto_trials(db, now=NOW)
    assert shared_position(db, tracker_id=old.id) is None
    db.commit()
    count = db.scalar(select(func.count()).select_from(LottoTrialEvent))
    advance_lotto_trials(db, now=NOW)
    assert db.scalar(select(func.count()).select_from(LottoTrialEvent)) == count
    assert lotto_trial_summary(db, now=NOW)['equity_cents'] == 50000


@pytest.mark.parametrize('winning_right', ['call', 'put'])
def test_both_directions_compete_for_one_slot_using_score_not_direction(db, winning_right):
    ensure_lotto_trials(db, SHARED_TRIAL_START)
    # Insert the loser first to ensure query/insertion order cannot pick the side.
    loser = tracker(db, 'QQQ', now=NOW, right='put' if winning_right == 'call' else 'call', score=80)
    winner = tracker(db, now=NOW, right=winning_right, score=99)
    advance_lotto_trials(db, now=NOW)
    quote(db, winner, NOW+timedelta(minutes=1))
    quote(db, loser, NOW+timedelta(minutes=1))
    advance_lotto_trials(db, now=NOW+timedelta(minutes=1))
    for rule in ('fixed5', 'trail40'):
        assert shared_position(db, rule, winner.id).status == 'OPEN'
        rejected = shared_position(db, rule, loser.id)
        assert rejected.status == 'SKIPPED' and 'CALL or PUT' in rejected.detail['reason']
        assert balance(db, key_for('both', rule)) == (47750, 0, 0)
    # Directional comparison still accepts its own idea independently.
    assert position(db, right=loser.right, tracker_id=loser.id).status == 'OPEN'


def test_shared_put_requires_put_evidence_and_no_old_provider_fallback(db):
    ensure_lotto_trials(db, SHARED_TRIAL_START)
    wrong = tracker(db, now=NOW, right='put')
    wrong.initial_snapshot = {'input_evidence': {'input_version': 'current-session-v2',
        'session_date': NOW.date().isoformat(), 'lottery_version': 'lotto-call-session-v2'}}
    old_provider = tracker(db, 'QQQ', now=NOW, provider='tradier')
    advance_lotto_trials(db, now=NOW)
    for row in (wrong, old_provider):
        assert shared_position(db, tracker_id=row.id).status == 'SKIPPED'
    assert balance(db, key_for('both', 'fixed5')) == (50000, 0, 0)


def test_exits_are_independent_and_realized_direction_totals_reconcile(db):
    first = enter(db)
    for minute, bid in [(2, 1.10), (3, .80)]:
        quote(db, first, NOW+timedelta(minutes=minute), bid, bid+.02)
        advance_lotto_trials(db, now=NOW+timedelta(minutes=minute))
    assert shared_position(db).status == 'UNSETTLED'
    assert shared_position(db, 'trail40').status == 'OPEN'
    # Fixed account can accept a PUT while trailing still holds its CALL.
    second = tracker(db, 'QQQ', now=NOW+timedelta(minutes=4), right='put')
    advance_lotto_trials(db, now=NOW+timedelta(minutes=4))
    quote(db, second, NOW+timedelta(minutes=5))
    advance_lotto_trials(db, now=NOW+timedelta(minutes=5))
    assert shared_position(db, tracker_id=second.id).status == 'OPEN'
    assert shared_position(db, 'trail40', second.id).status == 'SKIPPED'
    # Do not reuse unsettled proceeds: only remaining settled money pays the PUT.
    assert balance(db, key_for('both', 'fixed5')) == (45450, 7900, 5600)
    for minute, bid in [(6, 1.10), (7, 0)]:
        quote(db, second, NOW+timedelta(minutes=minute), bid, bid+.02)
        advance_lotto_trials(db, now=NOW+timedelta(minutes=minute))
    summary = lotto_trial_summary(db, now=NOW+timedelta(minutes=7))
    calls, puts = summary['direction_breakdown']
    assert calls['realized_cents'] == 5600 and calls['closed'] == 1
    assert puts['realized_cents'] == -2300 and puts['closed'] == 1
    assert sum(r['realized_cents'] for r in summary['direction_breakdown']) == summary['realized_cents'] == 3300
    assert summary['equity_cents'] == 53300
    # Reads across pages do not change the full-account directional totals or cash.
    assert lotto_trial_summary(db, page=99, now=NOW+timedelta(minutes=7))['direction_breakdown'] == summary['direction_breakdown']


@pytest.mark.parametrize('constraint', ['daily_cap', 'cash', 'ticker_day'])
def test_opposite_direction_shares_budget_cash_and_ticker_limit(db, constraint):
    ensure_lotto_trials(db, SHARED_TRIAL_START)
    key = key_for('both', 'fixed5')
    if constraint == 'cash':
        event(db, key, 'TEST_PRIOR_DEBIT', 'test:debit', NOW, settled=-49000)
    else:
        db.add(LottoTrialPosition(account_key=key, tracker_id='prior', status='UNSETTLED',
            detail={'symbol': 'SPY' if constraint == 'ticker_day' else 'OTHER', 'right': 'call',
                'date': NOW.date().isoformat(), 'entry_debit_cents': 8000, 'net_pnl_cents': 0}))
    db.flush()
    put = tracker(db, now=NOW, right='put')
    advance_lotto_trials(db, now=NOW)
    quote(db, put, NOW+timedelta(minutes=1))
    advance_lotto_trials(db, now=NOW+timedelta(minutes=1))
    assert shared_position(db, tracker_id=put.id).status == 'SKIPPED'
    # Other exit rule's separate budget is unaffected.
    assert shared_position(db, 'trail40', put.id).status == 'OPEN'


def test_unknown_call_blocks_new_put_without_fabricating_directional_loss(db):
    enter(db)
    advance_lotto_trials(db, now=NOW.replace(hour=20))
    tomorrow = NOW+timedelta(days=1)
    put = tracker(db, 'QQQ', now=tomorrow, right='put')
    advance_lotto_trials(db, now=tomorrow)
    assert shared_position(db, tracker_id=put.id).status == 'SKIPPED'
    summary = lotto_trial_summary(db, now=tomorrow)
    assert summary['equity_cents'] is None
    assert summary['direction_breakdown'][0]['unpriced'] == 1
    assert summary['direction_breakdown'][0]['realized_cents'] == 0
    assert summary['settled_cents'] == 47750
