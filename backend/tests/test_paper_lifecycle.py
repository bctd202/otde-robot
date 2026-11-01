"""Lifecycle events never substitute for missing financial evidence."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.db.models import (AutomatedOptionMark, ForwardPaperAccount, ForwardPaperEvent,
                           ForwardPaperPosition, ForwardPaperEquitySnapshot)
from app.services import expanded_account as expanded, paper_lifecycle as lifecycle, readiness
import test_expanded_account as fixtures
from test_expanded_account import activate, discover, fill, AllQuotes
from test_forward_account import START, candidate

db = fixtures.db
END = START.replace(hour=20, minute=0, second=0)


def first_position(db):
    return db.scalar(select(ForwardPaperPosition).where(ForwardPaperPosition.account_key == expanded.KEY))


def test_ended_missing_exit_releases_only_capacity_not_cash_or_missing_value(db, monkeypatch):
    account = activate(db); discover(db); fill(db)
    p = first_position(db)
    original = dict(p.detail)
    p.status = 'UNPRICED'; p.detail = {**original, 'reason': 'Original missing quote'}
    db.commit()
    policy = dict(account.policy)
    cash = expanded._balance(db)
    expanded.advance_account(db, now=END)
    assert p.status == lifecycle.ENDED_UNRESOLVED
    assert all(p.detail[k] == v for k, v in original.items())
    assert p.detail['reason'] == 'Original missing quote'
    assert 'sale_cents' not in p.detail and 'net_pnl_cents' not in p.detail
    assert expanded._balance(db) == cash and account.policy == policy
    result = expanded.account_summary(db, now=END)
    assert result['positions'] == []
    assert result['expired_unresolved_count'] == 1
    assert result['expired_unresolved_debit_cents'] == 4750
    assert result['unpriced_positions'] == 1 and result['equity_cents'] is None
    assert result['reserved_exit_fees_cents'] == 0
    assert result['realized_cents'] == 0
    assert result['unresolved_expirations'][0]['lifecycle_label'] == 'Session ended · exit price missing'
    assert result['unresolved_expirations'][0]['entry_dte'] == 0
    snapshot = db.scalar(select(ForwardPaperEquitySnapshot).where(
        ForwardPaperEquitySnapshot.observed_at == END))
    assert snapshot.equity_cents is None and snapshot.unpriced_positions == 1
    monkeypatch.setattr(readiness, 'get_settings', lambda: SimpleNamespace(
        paper_only=True, parlay_background_scanner_enabled=True))
    status = readiness.snapshot(db, object(), now=END)
    assert status['main_unknown_exits'] == status['main_expired_unresolved_exits'] == 1
    assert status['status'] == 'ATTENTION'


def test_restart_is_idempotent_old_events_and_snapshots_survive_and_get_is_nonmutating(db):
    activate(db); discover(db); fill(db); db.commit()
    original_events = [(e.id, e.kind, dict(e.detail)) for e in db.scalars(select(ForwardPaperEvent))]
    original_snapshots = [(s.id, s.equity_cents) for s in db.scalars(select(ForwardPaperEquitySnapshot))]
    for at in (END, END, END+timedelta(days=1)):
        expanded.advance_account(db, now=at)
        db.commit()
    events = list(db.scalars(select(ForwardPaperEvent).where(
        ForwardPaperEvent.kind.in_(('LIFECYCLE_BOUNDARY', 'SESSION_END_UNRESOLVED')))))
    assert len(events) == 2
    assert all((e.settled_cents, e.unsettled_cents, e.fee_cents, e.realized_cents) == (0, 0, 0, 0) for e in events)
    for key, kind, detail in original_events:
        event = db.get(ForwardPaperEvent, key)
        assert (event.kind, event.detail) == (kind, detail)
    for key, value in original_snapshots:
        assert db.get(ForwardPaperEquitySnapshot, key).equity_cents == value
    before = db.connection().connection.driver_connection.total_changes
    for page in (1, 2, 99):
        result = expanded.account_summary(db, now=END+timedelta(days=1), page=page)
        assert result['unresolved_expirations'][0]['lifecycle_label'] == 'Expired · exit price missing'
    assert db.connection().connection.driver_connection.total_changes == before


def test_reading_an_old_unknown_does_not_close_it_or_release_capacity(db):
    activate(db); discover(db); fill(db)
    p = first_position(db); p.status = 'UNPRICED'; db.commit()
    before = db.connection().connection.driver_connection.total_changes
    result = expanded.account_summary(db, now=END+timedelta(days=1))
    assert p.status == 'UNPRICED'
    assert result['expired_unresolved_count'] == 0
    assert len(result['positions']) == 1
    assert db.connection().connection.driver_connection.total_changes == before


def test_unknown_is_still_held_before_expiry_and_later_dated_contract_is_not_expired_early(db):
    activate(db); discover(db); fill(db)
    p = first_position(db)
    mark = db.get(AutomatedOptionMark, p.entry_mark_id)
    mark.expiration += timedelta(days=1)
    p.status = 'UNPRICED'; db.commit()
    expanded.advance_account(db, now=END)
    assert p.status == 'UNPRICED'
    assert expanded.account_summary(db, now=END)['reserved_exit_fees_cents'] == 50
    expanded.advance_account(db, now=END+timedelta(days=1))
    assert p.status == lifecycle.ENDED_UNRESOLVED


@pytest.mark.parametrize(('day', 'utc_hour'), [(date(2026, 10, 30), 20),
                                             (date(2026, 11, 2), 21),
                                             (date(2026, 11, 27), 18)])
def test_regular_session_boundary_respects_dst_and_early_close(day, utc_hour):
    mark = SimpleNamespace(expiration=day, trading_date=day)
    assert lifecycle.final_session_end(mark).astimezone(timezone.utc) == datetime(
        day.year, day.month, day.day, utc_hour, tzinfo=timezone.utc)


@pytest.mark.parametrize('bid', [0, .25])
def test_existing_timed_exit_records_later_verified_quote_before_close_including_zero_bid(db, bid):
    activate(db); trades = discover(db); fill(db)
    trades[0].exit_reason = 'TIMED_EXIT'
    trades[0].exit_at = END-timedelta(minutes=15)
    requested = trades[0].exit_at+timedelta(minutes=1)
    expanded.advance_account(db, AllQuotes(requested, bid=bid, ask=bid+.01), now=requested)
    assert first_position(db).status == 'OPEN'  # Same-decision quote cannot fill.
    later = requested+timedelta(seconds=2)
    expanded.advance_account(db, AllQuotes(later, bid=bid, ask=bid+.01), now=later)
    p = first_position(db)
    assert p.status == 'UNSETTLED' and 'sale_cents' in p.detail
    assert p.detail['sale_cents'] == max(0, round(bid*10000)-100)
    assert p.detail['net_pnl_cents'] == p.detail['sale_cents']-4800
    expanded.advance_account(db, now=END)
    assert p.status == 'UNSETTLED'  # A known sale must never become missing expiry.
    assert expanded.account_summary(db, now=END)['expired_unresolved_count'] == 0


def test_released_slots_accept_only_new_opportunities_without_replaying_skips_or_refunding_cash(db):
    activate(db); discover(db, 11); fill(db)
    skipped = db.scalar(select(ForwardPaperPosition).where(ForwardPaperPosition.status == 'SKIPPED'))
    cash = expanded._balance(db)
    expanded.advance_account(db, now=END)
    assert expanded._balance(db) == cash
    assert db.scalar(select(func.count()).select_from(ForwardPaperPosition).where(
        ForwardPaperPosition.status == lifecycle.ENDED_UNRESOLVED)) == 10
    next_day = START+timedelta(days=1)
    trade = candidate(db, 'new-day', 'NEW', now=next_day)
    trade.trading_date = next_day.date()
    mark = db.scalar(select(AutomatedOptionMark).where(AutomatedOptionMark.signal_id == 'new-day'))
    mark.option_symbol = mark.normalized_option_symbol = 'NEW260804C00100000'

    class NextDayQuotes(AllQuotes):
        def cached_option_chain(self, ticker, *_):
            return [self.quote.model_copy(update={'symbol': ticker, 'expiration': next_day.date(),
                'option_symbol': f'{ticker}260804C00100000', 'normalized_symbol': f'{ticker}260804C00100000'})]

    expanded.advance_account(db, NextDayQuotes(next_day), now=next_day)
    later = next_day+timedelta(seconds=2)
    expanded.advance_account(db, NextDayQuotes(later), now=later)
    new = db.scalar(select(ForwardPaperPosition).where(ForwardPaperPosition.signal_id == 'new-day'))
    assert new.status == 'OPEN' and skipped.status == 'SKIPPED'
    assert expanded._balance(db) == (cash[0]-4750, cash[1])
    assert expanded.account_summary(db, now=later)['equity_cents'] is None
    assert db.scalar(select(func.count()).select_from(ForwardPaperEvent).where(
        ForwardPaperEvent.account_key == expanded.KEY, ForwardPaperEvent.kind == 'FUNDING')) == 1


def test_original_account_processing_policy_and_positions_are_untouched(db):
    from app.services import forward_account as baseline
    activate(db)
    row = candidate(db, 'original-account')
    mark = db.scalar(select(AutomatedOptionMark).where(AutomatedOptionMark.signal_id == row.signal_id))
    old = ForwardPaperPosition(account_key=baseline.KEY, signal_id=row.signal_id, entry_mark_id=mark.id,
        status='UNPRICED', first_seen_at=START, detail={'entry_debit_cents': 4750, 'entry_fee_cents': 150})
    db.add(old); db.commit()
    policy = dict(db.get(ForwardPaperAccount, baseline.KEY).policy)
    expanded.advance_account(db, now=END+timedelta(days=1))
    assert old.status == 'UNPRICED'
    assert db.get(ForwardPaperAccount, baseline.KEY).policy == policy
