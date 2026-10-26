"""The contract ceiling is not a daily budget; legacy trials remain immutable."""
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.models import LottoTrialAccount, LottoTrialEvent, LottoTrialPosition
from app.db.session import Base
from app.services.lotto_trials import (SHARED_TRIAL_START, activate_multi_trials, advance_lotto_trials,
    balance, ensure_lotto_trials, event, key_for, lotto_trial_summary, multi_key)
from tests.test_lotto_trials import quote, tracker

NOW = SHARED_TRIAL_START+timedelta(minutes=30)


@pytest.fixture
def db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def candidate(db, symbol='SPY', right='call', now=NOW):
    row = tracker(db, symbol, right=right, now=now)
    evidence = dict(row.initial_snapshot['input_evidence'])
    evidence.update(lottery_version=f'lotto-{right}-session-v3', contract_premium_cap_cents=10000)
    row.initial_snapshot = {'input_evidence': evidence}
    db.flush()
    return row


def pos(db, tracker_id, rule='fixed5'):
    return db.scalar(select(LottoTrialPosition).where(
        LottoTrialPosition.account_key == multi_key(rule), LottoTrialPosition.tracker_id == tracker_id))


def test_explicit_once_only_activation_no_import_and_read_only(db):
    ensure_lotto_trials(db, NOW)
    legacy = [(a.key, dict(a.policy), a.activated_at) for a in db.scalars(select(LottoTrialAccount))]
    old = candidate(db, now=NOW-timedelta(minutes=1))
    for _ in range(2):
        assert lotto_trial_summary(db, multi_key('fixed5'), now=NOW)['activation_required']
        advance_lotto_trials(db, now=NOW)
    assert db.get(LottoTrialAccount, multi_key('fixed5')) is None
    activate_multi_trials(db, now=NOW)
    db.commit()
    before = db.scalar(select(func.count()).select_from(LottoTrialEvent))
    activate_multi_trials(db, now=NOW+timedelta(days=1))
    assert db.scalar(select(func.count()).select_from(LottoTrialEvent)) == before
    for key, policy, activated in legacy:
        a = db.get(LottoTrialAccount, key)
        assert a.policy == policy and a.activated_at == activated.replace(tzinfo=None)
    advance_lotto_trials(db, now=NOW)
    assert pos(db, old.id) is None
    summary = lotto_trial_summary(db, now=NOW)
    assert summary['account_key'] == multi_key('fixed5') and summary['equity_cents'] == 50000
    assert summary['policy']['daily_debit_cap_cents'] is None
    assert not lotto_trial_summary(db, key_for('both', 'fixed5'), now=NOW)['accepting_new_discoveries']


@pytest.mark.parametrize('ask,accepted', [(1.0, True), (1.0001, False), (1.01, False), (.75, True)])
def test_premium_boundary_excludes_fees_and_slippage(db, ask, accepted):
    activate_multi_trials(db, now=NOW)
    row = candidate(db)
    advance_lotto_trials(db, now=NOW)
    quote(db, row, NOW+timedelta(seconds=1), ask-.02, ask)
    advance_lotto_trials(db, now=NOW+timedelta(seconds=1))
    p = pos(db, row.id)
    assert p.status == ('OPEN' if accepted else 'SKIPPED')
    if accepted and ask == 1:
        assert p.detail['entry_debit_cents'] == 10250
        assert balance(db, multi_key('fixed5'))[0] == 39750
    if not accepted:
        assert 'premium exceeds $100' in p.detail['reason']


def test_five_slots_both_rights_and_spending_above_100(db):
    activate_multi_trials(db, now=NOW)
    rows = [candidate(db, f'T{i}', right='call' if i%2 else 'put') for i in range(6)]
    advance_lotto_trials(db, now=NOW)
    assert sum(pos(db, r.id).status == 'PENDING_ENTRY' for r in rows) == 5
    for r in rows:
        quote(db, r, NOW+timedelta(minutes=1), .38, .40)
    advance_lotto_trials(db, now=NOW+timedelta(minutes=1))
    assert sum(pos(db, r.id).status == 'OPEN' for r in rows) == 5
    assert balance(db, multi_key('fixed5')) == (28750, 0, 0)  # $212.50 spent, not capped at $100/day
    assert 'five account slots' in pos(db, rows[-1].id).detail['reason']
    before = db.scalar(select(func.count()).select_from(LottoTrialEvent))
    db.commit()
    db.expire_all()
    advance_lotto_trials(db, now=NOW+timedelta(minutes=1))
    assert db.scalar(select(func.count()).select_from(LottoTrialEvent)) == before
    summary = lotto_trial_summary(db, now=NOW+timedelta(minutes=1), view='ENTERED')
    assert summary['pagination']['total'] == 5
    assert summary['reserved_closing_costs_cents'] == 250
    skipped = lotto_trial_summary(db, now=NOW+timedelta(minutes=1), view='SKIPPED')
    assert skipped['pagination']['total'] == 1
    assert summary['direction_breakdown'] == skipped['direction_breakdown']


def test_reserves_unknown_exit_costs_and_never_reuses_unsettled_cash(db):
    activate_multi_trials(db, now=NOW)
    key = multi_key('fixed5')
    event(db, key, 'FIXTURE', 'prior-debit', NOW, settled=-47700, unsettled=10000)
    db.add(LottoTrialPosition(account_key=key, tracker_id='old', status='UNPRICED',
        detail={'symbol':'OLD','right':'call','date':NOW.date().isoformat(),'entry_debit_cents':1000}))
    row = candidate(db)
    advance_lotto_trials(db, now=NOW)
    quote(db, row, NOW+timedelta(minutes=1))
    advance_lotto_trials(db, now=NOW+timedelta(minutes=1))
    # $23 cash cannot cover $22.50 debit plus two $0.50 closing reserves.
    assert pos(db, row.id).status == 'SKIPPED'
    assert 'settled cash' in pos(db, row.id).detail['reason']
    assert pos(db, row.id, 'trail40').status == 'OPEN'
    assert lotto_trial_summary(db, now=NOW)['equity_cents'] is None


def test_unknown_positions_use_slots_and_same_ticker_cannot_double_enter(db):
    activate_multi_trials(db, now=NOW)
    key = multi_key('fixed5')
    for i in range(4):
        db.add(LottoTrialPosition(account_key=key, tracker_id=f'old{i}', status='UNPRICED', detail={}))
    call = candidate(db, right='call')
    put = candidate(db, right='put')
    advance_lotto_trials(db, now=NOW)
    assert pos(db, call.id).status == 'PENDING_ENTRY'
    assert pos(db, put.id).status == 'SKIPPED'
    assert 'ticker/day' in pos(db, put.id, 'trail40').detail['reason']


def test_retired_positions_still_exit_and_pending_deadline_remains(db):
    from tests.test_shared_lotto_trials import enter, shared_position
    old = enter(db)
    activate_multi_trials(db, now=NOW+timedelta(minutes=2))
    for minute, bid in [(3, 1.1), (4, .8)]:
        quote(db, old, NOW+timedelta(minutes=minute), bid, bid+.02)
        advance_lotto_trials(db, now=NOW+timedelta(minutes=minute))
    assert shared_position(db, tracker_id=old.id).status == 'UNSETTLED'
    fresh = candidate(db, 'QQQ', now=NOW+timedelta(minutes=5))
    advance_lotto_trials(db, now=NOW+timedelta(minutes=5))
    quote(db, fresh, NOW+timedelta(minutes=8))
    advance_lotto_trials(db, now=NOW+timedelta(minutes=8))
    assert pos(db, fresh.id).status == 'SKIPPED'
    assert 'deadline' in pos(db, fresh.id).detail['reason']
    assert shared_position(db, tracker_id=fresh.id) is None


@pytest.mark.parametrize('ask,expected', [(1.0, 1), (1.01, 0)])
def test_scanner_cap_changes_only_after_explicit_activation(db, ask, expected):
    from tests.test_lottery_tracker import LiveLotteryProvider
    from app.services.lottery_tracker import track_lottery_scan

    class Tasty(LiveLotteryProvider):
        def status(self):
            return super().status().model_copy(update={'provider':'tastytrade'})

        def option_chain(self, symbol, expiration=None):
            return [row.model_copy(update={'provider':'tastytrade'}) for row in super().option_chain(symbol, expiration)]

    provider = Tasty()
    provider.now, provider.ask, provider.bid = NOW, ask, ask-.02
    assert track_lottery_scan(db, provider, ['SPY'], NOW-timedelta(minutes=1), now=NOW) == []
    activate_multi_trials(db, now=NOW)
    found = track_lottery_scan(db, provider, ['SPY'], NOW-timedelta(minutes=1), now=NOW)
    assert len(found) == expected
    if found:
        assert found[0].initial_snapshot['input_evidence']['contract_premium_cap_cents'] == 10000
        assert found[0].initial_snapshot['input_evidence']['lottery_version'] == 'lotto-call-session-v3'


def test_filtered_pagination_is_read_only_and_account_totals_do_not_depend_on_page(db):
    activate_multi_trials(db, now=NOW)
    key = multi_key('fixed5')
    for index in range(15):
        db.add(LottoTrialPosition(account_key=key, tracker_id=f'skip{index}', status='SKIPPED',
            detail={'symbol':f'T{index}', 'right':'call'}))
    db.commit()
    count = db.scalar(select(func.count()).select_from(LottoTrialEvent))
    empty = lotto_trial_summary(db, now=NOW, view='ENTERED')
    pending = lotto_trial_summary(db, now=NOW, view='PENDING')
    second = lotto_trial_summary(db, now=NOW, view='SKIPPED', page=2)
    assert empty['trades'] == pending['trades'] == []
    assert second['pagination'] == {'page':2, 'pages':2, 'total':15}
    assert len(second['trades']) == 3
    assert empty['direction_breakdown'] == second['direction_breakdown']
    assert not db.dirty and not db.new
    assert db.scalar(select(func.count()).select_from(LottoTrialEvent)) == count
    with pytest.raises(ValueError):
        lotto_trial_summary(db, now=NOW, view='BOGUS')


def test_multi_exit_variants_remain_independent_and_later_quote_only(db):
    activate_multi_trials(db, now=NOW)
    row = candidate(db)
    quote(db, row, NOW)
    advance_lotto_trials(db, now=NOW)
    assert pos(db, row.id).status == 'PENDING_ENTRY'
    quote(db, row, NOW+timedelta(minutes=1))
    advance_lotto_trials(db, now=NOW+timedelta(minutes=1))
    quote(db, row, NOW+timedelta(minutes=2), 1.10, 1.12)
    advance_lotto_trials(db, now=NOW+timedelta(minutes=2))
    assert pos(db, row.id).status == 'OPEN'  # Trigger quote is never the fill.
    quote(db, row, NOW+timedelta(minutes=3), .80, .82)
    advance_lotto_trials(db, now=NOW+timedelta(minutes=3))
    assert pos(db, row.id).status == 'UNSETTLED'
    assert pos(db, row.id, 'trail40').status == 'OPEN'
    assert pos(db, row.id).detail['net_pnl_cents'] == 5600
