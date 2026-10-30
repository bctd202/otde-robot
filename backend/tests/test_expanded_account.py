"""Synthetic quotes only; never backfilled into a live research ledger."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.db.models import ForwardPaperAccount, ForwardPaperEvent, ForwardPaperPosition
from app.services import expanded_account as expanded, forward_account as baseline
from test_forward_account import Quotes, START, candidate
from test_performance import database

REVISION = 'a' * 40
ACTIVATION = START.replace(hour=12)


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setattr(baseline, 'TRIAL_START', ACTIVATION-timedelta(days=1))
    monkeypatch.setattr(expanded, 'get_settings', lambda: SimpleNamespace(paper_only=True, market_data_provider='tastytrade'))
    with database()() as session:
        baseline.ensure_account(session, ACTIVATION)
        session.commit()
        yield session


def activate(db):
    value = expanded.activate(db, revision=REVISION, now=ACTIVATION)
    db.commit()
    return value


class AllQuotes(Quotes):
    def cached_option_chain(self, ticker, *_):
        return [self.quote.model_copy(update={'symbol': ticker, 'option_symbol': f'{ticker}260803C00100000',
                                              'normalized_symbol': f'{ticker}260803C00100000'})]


def discover(db, count=1):
    trades = [candidate(db, f'trade-{i}', f'T{i}') for i in range(count)]
    expanded.advance_account(db, AllQuotes(START), now=START)
    return trades


def fill(db):
    at = START+timedelta(seconds=2)
    expanded.advance_account(db, AllQuotes(at), now=at)
    return at


def test_dormant_reads_and_housekeeping_do_not_activate(db):
    expanded.advance_account(db, now=START)
    assert expanded.refresh_account_quotes(db, AllQuotes(START), now=START) == 0
    result = expanded.account_summary(db)
    assert result['status'] == 'NOT_STARTED' and result['activation_required']
    assert db.get(ForwardPaperAccount, expanded.KEY) is None
    assert db.scalar(select(func.count()).select_from(ForwardPaperEvent)) == 1


def test_activation_is_prospective_independent_idempotent_and_preserves_old_unknowns(db):
    old = db.get(ForwardPaperAccount, baseline.KEY)
    policy = dict(old.policy)
    candidate(db, 'historical', now=ACTIVATION-timedelta(minutes=1))
    old_pos = ForwardPaperPosition(account_key=baseline.KEY, signal_id='historical', entry_mark_id=1,
        status='UNPRICED', first_seen_at=ACTIVATION, detail={'entry_debit_cents':4750, 'entry_fee_cents':150})
    db.add(old_pos); db.commit()
    new = activate(db)
    assert new.policy['max_positions'] == 10 and new.policy['starting_cash_cents'] == 200000
    assert new.mark_watermark == 1
    assert expanded.activate(db, revision=REVISION, now=START) is new  # Retry cannot reset it.
    expanded.advance_account(db, now=START)
    assert db.scalar(select(func.count()).select_from(ForwardPaperPosition)) == 1
    assert old_pos.status == 'UNPRICED' and old.policy == policy
    assert baseline._balance(db) == (200000, 0)
    assert expanded._balance(db) == (200000, 0)
    assert db.scalar(select(func.count()).select_from(ForwardPaperEvent).where(
        ForwardPaperEvent.account_key == expanded.KEY, ForwardPaperEvent.kind == 'FUNDING')) == 1


@pytest.mark.parametrize('mode', ['market', 'revision', 'provider', 'live', 'policy'])
def test_activation_rejects_unreviewed_or_unsafe_context(db, monkeypatch, mode):
    now = START if mode == 'market' else ACTIVATION
    revision = 'main' if mode == 'revision' else REVISION
    if mode in ('provider', 'live'):
        monkeypatch.setattr(expanded, 'get_settings', lambda: SimpleNamespace(
            paper_only=mode != 'live', market_data_provider='mock' if mode == 'provider' else 'tastytrade'))
    if mode == 'policy':
        old = db.get(ForwardPaperAccount, baseline.KEY)
        old.policy = {**old.policy, 'max_positions':5}; db.flush()
    with pytest.raises(ValueError):
        expanded.activate(db, revision=revision, now=now)
    assert db.get(ForwardPaperAccount, expanded.KEY) is None


def test_ten_concurrent_fills_eleventh_is_logged_and_read_only_pages_preserve_cash(db):
    activate(db)
    discover(db, 11)
    assert not db.scalar(select(ForwardPaperPosition.id).where(ForwardPaperPosition.status == 'OPEN'))
    now = fill(db)
    result = expanded.account_summary(db, now=now)
    assert sum(p['status'] == 'OPEN' for p in result['positions']) == 10
    assert result['trade_pagination']['total'] == 11
    assert sum(p['status'] == 'SKIPPED' for p in result['trades']) == 1
    assert result['settled_cents'] == 152500
    assert result['reserved_exit_fees_cents'] == 500
    assert result['available_cents'] == 152000
    assert db.get(ForwardPaperAccount, baseline.KEY).policy['max_positions'] == 3
    db.commit()
    events = db.scalar(select(func.count()).select_from(ForwardPaperEvent))
    for page in (1, 2, 99):
        expanded.account_summary(db, page=page, now=now)
    expanded.advance_account(db, AllQuotes(now), now=now)
    assert db.scalar(select(func.count()).select_from(ForwardPaperEvent)) == events
    assert expanded._balance(db) == (152500, 0)


def test_unknown_exit_consumes_slot_and_is_never_released_as_zero(db):
    activate(db); discover(db, 10); fill(db)
    positions = list(db.scalars(select(ForwardPaperPosition).where(ForwardPaperPosition.account_key == expanded.KEY)))
    positions[0].status = 'UNPRICED'
    candidate(db, 'eleventh', 'EXTRA', now=START+timedelta(seconds=4))
    expanded.advance_account(db, AllQuotes(START+timedelta(seconds=4)), now=START+timedelta(seconds=4))
    new = db.scalar(select(ForwardPaperPosition).where(ForwardPaperPosition.signal_id == 'eleventh'))
    assert new.status == 'SKIPPED' and 'Concurrent' in new.detail['reason']
    result = expanded.account_summary(db, now=START+timedelta(seconds=4))
    assert result['equity_cents'] is None and result['unpriced_positions'] == 1
    assert positions[0].status == 'UNPRICED'


@pytest.mark.parametrize('change', [dict(received_at=START), dict(receipt_basis='UNKNOWN'), dict(provider='tradier')])
def test_stale_repeated_or_wrong_provider_quotes_do_not_fill(db, change):
    activate(db); discover(db)
    now = START+timedelta(seconds=2)
    expanded.advance_account(db, AllQuotes(now, **change), now=now)
    assert db.scalar(select(ForwardPaperPosition)).status == 'PENDING_ENTRY'
    expired = START+timedelta(seconds=121)
    expanded.advance_account(db, AllQuotes(expired), now=expired)
    assert db.scalar(select(ForwardPaperPosition)).status == 'SKIPPED'
    assert expanded._balance(db) == (200000, 0)


def test_exit_fees_settlement_and_restart_are_preserved(db):
    activate(db); trades = discover(db); fill(db)
    trades[0].exit_reason = 'TARGET'; trades[0].exit_at = START+timedelta(minutes=1)
    decision = trades[0].exit_at+timedelta(minutes=1)
    expanded.advance_account(db, AllQuotes(decision, bid=.75, ask=.80), now=decision)
    assert db.scalar(select(ForwardPaperPosition)).status == 'OPEN'
    at = decision+timedelta(seconds=2)
    expanded.advance_account(db, AllQuotes(at, bid=.75, ask=.80), now=at)
    result = expanded.account_summary(db, now=at)
    assert result['realized_cents'] == 2600 and result['unsettled_cents'] == 7400
    assert result['equity_cents'] == 202600 and result['reserved_exit_fees_cents'] == 0
    db.commit()
    due = expanded.settlement_at(at)
    expanded.advance_account(db, now=due)
    expanded.advance_account(db, now=due)
    assert expanded._balance(db) == (202600, 0)
    assert db.scalar(select(ForwardPaperPosition)).status == 'CLOSED'


@pytest.mark.parametrize('remaining,expected', [(100,6),(21,1),(20,0)])
def test_refresh_is_bounded_and_reserves_baseline_requests(db, remaining, expected):
    class Provider(AllQuotes):
        calls = 0
        def cached_option_chain(self, *_): return None
        def budget_status(self): return {'remaining':remaining-self.calls}
        def option_chain(self, *_): self.calls += 1
    activate(db)
    for i in range(12): candidate(db, str(i), f'T{i}')
    provider = Provider(START)
    assert expanded.refresh_account_quotes(db, provider, now=START) == expected
    assert provider.calls == expected


def test_old_account_is_still_active_and_new_is_not_mislabeled_archived(db):
    activate(db)
    assert expanded.account_summary(db, account_key=baseline.KEY)['status'] == 'ACTIVE'
    result = expanded.account_summary(db)
    assert result['status'] == 'ACTIVE'
    assert len([a for a in result['accounts'] if a['key'] == expanded.KEY]) == 1
    assert not next(a for a in result['accounts'] if a['key'] == expanded.KEY)['archived']


def test_route_defaults_to_new_account_without_activating(db):
    from app.api.routes import forward_paper_account
    result = forward_paper_account(db=db)
    assert result['account_key'] == expanded.KEY and result['status'] == 'NOT_STARTED'
    assert db.get(ForwardPaperAccount, expanded.KEY) is None


def test_more_slots_do_not_bypass_cash_or_closing_reserve(db):
    activate(db)
    # Synthetic fixture leaves enough for entry, but not its closing reserve.
    expanded._event(db, 'TEST_CASH', 'fixture', ACTIVATION, settled=4750-200000)
    discover(db); fill(db)
    p = db.scalar(select(ForwardPaperPosition))
    assert p.status == 'SKIPPED' and p.detail['reason'] == 'Insufficient settled buying power'
    assert expanded._balance(db) == (4750, 0)


@pytest.mark.parametrize('fail', [False, True])
def test_scanner_services_frozen_study_first_and_isolates_new_account_failure(db, monkeypatch, fail):
    from app.services import signal_engine, retest_trials
    from app.schemas.market import ProviderStatus
    from app.db.models import SignalScan
    activate(db)
    order = []
    feed = AllQuotes(START)
    monkeypatch.setattr(feed, 'status', lambda: ProviderStatus(provider='tastytrade', mode='live',
        status='healthy', delay_seconds=0, latest_timestamp=START, message='Synthetic test'))
    for name in ('rank_parlays', 'rank_structured_intraday'):
        monkeypatch.setattr(signal_engine, name, lambda *a, **kw: [])
    for name in ('track_candidates', 'track_lottery_scan', 'record_option_observations',
                 'advance_account', 'advance_lotto_trials', '_position_alerts', '_performance_alerts'):
        monkeypatch.setattr(signal_engine, name, lambda *a, **kw: None)
    monkeypatch.setattr(signal_engine, 'refresh_account_quotes', lambda *a, **kw: order.append('baseline'))
    monkeypatch.setattr(retest_trials, 'active', lambda *a: True)
    monkeypatch.setattr(retest_trials, 'refresh_quotes', lambda *a, **kw: order.append('retest-quotes'))
    monkeypatch.setattr(retest_trials, 'process', lambda *a, **kw: order.append('retest-process'))
    monkeypatch.setattr(expanded, 'refresh_account_quotes', lambda *a, **kw: order.append('expanded-quotes'))
    def advance(session, *a, **kw):
        order.append('expanded-process')
        if fail:
            expanded._event(session, 'TEST_FAILED_WRITE', 'rollback-me', START)
            raise ValueError('Synthetic account failure')
    monkeypatch.setattr(expanded, 'advance_account', advance)
    result = signal_engine.run_signal_scan(db, feed, ['SPY'], evaluation_at=START)
    assert result is not None and db.get(SignalScan, result.id) is not None
    assert order == ['baseline', 'retest-quotes', 'retest-process', 'expanded-quotes', 'expanded-process']
    assert not db.scalar(select(ForwardPaperEvent.id).where(ForwardPaperEvent.kind == 'TEST_FAILED_WRITE'))
    assert expanded._balance(db) == (200000, 0)
