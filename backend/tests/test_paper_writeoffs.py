"""Explicit synthetic paper adjustments: no inferred sales, cash credits or backfill."""
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.db.models import (AutomatedOptionMark, ForwardPaperAccount, ForwardPaperEquitySnapshot,
                           ForwardPaperEvent, ForwardPaperPosition, SignalPerformance)
from app.services import expanded_account as expanded, forward_account as baseline, paper_writeoffs as writeoffs
from app.services import readiness
import test_expanded_account as fixtures
from test_expanded_account import activate, discover, fill
from test_forward_account import START

db = fixtures.db
END = START.replace(hour=20, minute=0, second=0)
ADJUSTED_AT = END+timedelta(minutes=1)


def ended(db, count=3):
    activate(db)
    discover(db, count)
    fill(db)
    expanded.advance_account(db, now=END)
    db.commit()
    return list(db.scalars(select(ForwardPaperPosition).where(
        ForwardPaperPosition.account_key == expanded.KEY).order_by(ForwardPaperPosition.id)))


def request(db, positions):
    return writeoffs.prepare_request(db, symbols=[p.detail['option_symbol'] for p in positions],
                                    expected_total_cents=sum(p.detail['entry_debit_cents'] for p in positions),
                                    approval_ref='synthetic-operator-explicit-write-off-approval')


def preserved(db):
    return {
        'events': [(e.id, e.kind, e.realized_cents, deepcopy(e.detail)) for e in db.scalars(
            select(ForwardPaperEvent).order_by(ForwardPaperEvent.id))],
        'snapshots': [(s.id, s.equity_cents, deepcopy(s.detail)) for s in db.scalars(
            select(ForwardPaperEquitySnapshot).order_by(ForwardPaperEquitySnapshot.id))],
        'signals': [(s.signal_id, s.result_r, s.exit_reason) for s in db.scalars(select(SignalPerformance))],
        'quotes': [(m.id, m.mark_status, m.bid, m.ask) for m in db.scalars(select(AutomatedOptionMark))],
    }


def test_three_writeoffs_book_full_cost_once_without_debiting_cash_again(db):
    positions = ended(db)
    before = preserved(db)
    details = {p.id: deepcopy(p.detail) for p in positions}
    original_cash = expanded._balance(db)
    baseline_cash = baseline._balance(db)
    policy = deepcopy(db.get(ForwardPaperAccount, expanded.KEY).policy)
    total = sum(p.detail['entry_debit_cents'] for p in positions)
    result = writeoffs.apply_request(db, request(db, positions), now=ADJUSTED_AT)
    db.commit()
    assert result['applied'] == 3 and result['loss_cents'] == total == 14250
    assert result['cash_delta_cents'] == 0
    assert expanded._balance(db) == original_cash and baseline._balance(db) == baseline_cash
    assert db.get(ForwardPaperAccount, expanded.KEY).policy == policy
    events = list(db.scalars(select(ForwardPaperEvent).where(ForwardPaperEvent.kind == writeoffs.EVENT)))
    assert len(events) == 3
    assert sum(e.realized_cents for e in events) == -total
    assert all((e.settled_cents, e.unsettled_cents, e.fee_cents) == (0, 0, 0) for e in events)
    for p in positions:
        assert p.status == writeoffs.STATUS
        assert all(p.detail[k] == v for k, v in details[p.id].items())
        assert not {'sale_cents', 'exit_quote', 'exit_at'} & p.detail.keys()
        event = next(e for e in events if e.detail['position_id'] == p.id)
        assert event.detail['original_detail'] == details[p.id]
        assert event.detail['actual_exit_verified'] is False
    after = preserved(db)
    assert after['events'][:len(before['events'])] == before['events']
    assert after['snapshots'][:len(before['snapshots'])] == before['snapshots']
    assert after['signals'] == before['signals'] and after['quotes'] == before['quotes']
    summary = expanded.account_summary(db, now=ADJUSTED_AT)
    assert summary['realized_cents'] == -total
    assert summary['confirmed_realized_cents'] == 0
    assert summary['equity_cents'] == 200000-total
    assert summary['write_off_adjustments']['loss_cents'] == total
    assert summary['write_off_adjustments']['count'] == 3
    assert summary['complete_verified_account_return'] is False
    assert summary['expired_unresolved_count'] == summary['unpriced_positions'] == 0
    assert all(t['net_proceeds_cents'] is None for t in summary['trades'])
    assert 'Manual write-off' in summary['trades'][0]['lifecycle_label']
    points = summary['equity_history']['intraday']
    assert points[-2]['equity_cents'] is None and points[-1]['equity_cents'] == 200000-total
    assert points[-2]['manual_write_off_count'] == 0 and points[-1]['manual_write_off_count'] == 3


def test_exact_retry_cannot_double_book_and_reads_never_mutate(db):
    positions = ended(db)
    plan = request(db, positions)
    writeoffs.apply_request(db, plan, now=ADJUSTED_AT)
    db.commit()
    before = preserved(db)
    result = writeoffs.apply_request(db, plan, now=ADJUSTED_AT+timedelta(seconds=1))
    db.commit()
    assert result['applied'] == 0 and result['already_applied'] == 3
    assert preserved(db) == before
    changed = db.connection().connection.driver_connection.total_changes
    for page in (1, 2, 99):
        expanded.account_summary(db, now=ADJUSTED_AT, page=page)
        writeoffs.adjustment_summary(db, expanded.KEY)
    assert db.connection().connection.driver_connection.total_changes == changed


@pytest.mark.parametrize('change', ['cost', 'symbol', 'hash', 'status', 'sale', 'entry_cash', 'account'])
def test_batch_is_all_or_nothing_if_any_target_changed(db, change):
    positions = ended(db)
    plan = request(db, positions)
    p = positions[-1]
    if change == 'cost': p.detail = {**p.detail, 'entry_debit_cents': 9999}
    if change == 'symbol': p.detail = {**p.detail, 'option_symbol': 'different'}
    if change == 'hash': p.detail = {**p.detail, 'reason': 'new evidence'}
    if change == 'status': p.status = 'OPEN'
    if change == 'sale': p.detail = {**p.detail, 'sale_cents': 100, 'exit_quote': {'bid': 1}}
    if change == 'entry_cash':
        event = db.scalar(select(ForwardPaperEvent).where(
            ForwardPaperEvent.account_key == expanded.KEY, ForwardPaperEvent.event_key == f'{p.id}:entry'))
        event.settled_cents = -1
    if change == 'account': p.account_key = baseline.KEY
    db.commit()
    with pytest.raises(ValueError):
        writeoffs.apply_request(db, plan, now=ADJUSTED_AT)
    db.commit()  # Even callers that catch errors cannot accidentally commit a partial batch.
    assert not db.scalar(select(ForwardPaperEvent.id).where(ForwardPaperEvent.kind == writeoffs.EVENT))
    assert not any(p.status == writeoffs.STATUS for p in positions)


def test_caller_rollback_undoes_entire_adjustment_even_from_fresh_transaction(db):
    positions = ended(db, 1)
    plan = request(db, positions)
    db.commit()
    writeoffs.apply_request(db, plan, now=ADJUSTED_AT)
    db.rollback()
    assert db.get(ForwardPaperPosition, positions[0].id).status == 'ENDED_UNRESOLVED'
    assert not db.scalar(select(ForwardPaperEvent.id).where(ForwardPaperEvent.kind == writeoffs.EVENT))


def test_open_longer_dated_or_backdated_targets_are_rejected(db):
    positions = ended(db, 1)
    plan = request(db, positions)
    with pytest.raises(ValueError, match='backdated'):
        writeoffs.apply_request(db, plan, now=END-timedelta(seconds=1))
    mark = db.get(AutomatedOptionMark, positions[0].entry_mark_id)
    mark.expiration += timedelta(days=1)
    db.commit()
    with pytest.raises(ValueError, match='refused'):
        writeoffs.apply_request(db, plan, now=ADJUSTED_AT)


def test_no_auto_writeoff_for_a_later_unknown_or_other_account(db):
    positions = ended(db, 2)
    writeoffs.apply_request(db, request(db, positions[:1]), now=ADJUSTED_AT)
    db.commit()
    expanded.advance_account(db, now=ADJUSTED_AT+timedelta(minutes=1))
    result = expanded.account_summary(db, now=ADJUSTED_AT+timedelta(minutes=1))
    assert positions[0].status == writeoffs.STATUS
    assert positions[1].status == 'ENDED_UNRESOLVED'
    assert result['unpriced_positions'] == 1 and result['equity_cents'] is None
    assert result['write_off_adjustments']['count'] == 1


def test_unknown_evidence_remains_visible_in_readiness_after_adjustment(db, monkeypatch):
    positions = ended(db, 1)
    writeoffs.apply_request(db, request(db, positions), now=ADJUSTED_AT)
    db.commit()
    monkeypatch.setattr(readiness, 'get_settings', lambda: SimpleNamespace(
        paper_only=True, parlay_background_scanner_enabled=True))
    result = readiness.snapshot(db, object(), now=ADJUSTED_AT)
    assert result['main_unknown_exits'] == 0 and result['main_manual_write_offs'] == 1
    assert any('actual exits remain unverified' in p for p in result['problems'])


def test_plan_refuses_wrong_total_and_conflicting_duplicate_approval(db):
    positions = ended(db, 1)
    with pytest.raises(ValueError, match='total'):
        writeoffs.prepare_request(db, symbols=[positions[0].detail['option_symbol']],
                                  expected_total_cents=1, approval_ref='explicit')
    plan = request(db, positions)
    writeoffs.apply_request(db, plan, now=ADJUSTED_AT)
    db.commit()
    changed = {**plan, 'approval_ref': 'different request'}
    with pytest.raises(ValueError, match='Conflicting'):
        writeoffs.apply_request(db, changed, now=ADJUSTED_AT)


def test_unsafe_config_or_different_account_cannot_writeoff(db, monkeypatch):
    positions = ended(db, 1)
    plan = request(db, positions)
    monkeypatch.setattr(writeoffs, 'get_settings', lambda: SimpleNamespace(paper_only=False))
    with pytest.raises(ValueError, match='Paper-only'):
        writeoffs.apply_request(db, plan, now=ADJUSTED_AT)
    monkeypatch.setattr(writeoffs, 'get_settings', lambda: SimpleNamespace(paper_only=True))
    with pytest.raises(ValueError, match='unsupported'):
        writeoffs.apply_request(db, {**plan, 'account_key': baseline.KEY}, now=ADJUSTED_AT)


def test_queued_older_scan_cannot_backdate_writeoff_assumptions(db):
    positions = ended(db, 1)
    writeoffs.apply_request(db, request(db, positions), now=ADJUSTED_AT)
    db.commit()
    original = preserved(db)
    expanded.advance_account(db, now=ADJUSTED_AT-timedelta(seconds=1))
    db.commit()
    assert preserved(db) == original


def test_retry_detects_modified_original_evidence(db):
    positions = ended(db, 1)
    plan = request(db, positions)
    writeoffs.apply_request(db, plan, now=ADJUSTED_AT)
    db.commit()
    positions[0].detail = {**positions[0].detail, 'entry_debit_cents': 1}
    db.commit()
    with pytest.raises(ValueError, match='Conflicting'):
        writeoffs.apply_request(db, plan, now=ADJUSTED_AT)
