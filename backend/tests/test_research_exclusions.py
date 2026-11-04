"""A read-only exact cohort exclusion is not a cash refund or a gap-removal rule."""
from copy import deepcopy
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.models import AutomatedOptionMark, ForwardPaperEquitySnapshot, ForwardPaperPosition
from app.services import expanded_account as expanded, paper_writeoffs, research_exclusions as research
import test_expanded_account as fixtures
from test_expanded_account import activate, discover, fill
from test_forward_account import START
from test_paper_writeoffs import preserved

db = fixtures.db
END = START.replace(hour=20, minute=0, second=0)
NOW = END+timedelta(minutes=1)


def approved(db, monkeypatch, count=3):
    activate(db)
    discover(db, count)
    fill(db)
    expanded.advance_account(db, now=END)
    db.commit()
    positions = list(db.scalars(select(ForwardPaperPosition).where(
        ForwardPaperPosition.account_key == expanded.KEY).order_by(ForwardPaperPosition.id)))
    selected = positions[:3]
    amount = sum(p.detail['entry_debit_cents'] for p in selected)
    request = paper_writeoffs.prepare_request(db, symbols=[p.detail['option_symbol'] for p in selected],
        expected_total_cents=amount, approval_ref='synthetic-exact-exclusion-test')
    result = paper_writeoffs.apply_request(db, request, now=NOW)
    db.commit()
    monkeypatch.setattr(research, 'APPROVAL_REQUEST_SHA256', result['request_sha256'])
    monkeypatch.setattr(research, 'EXPECTED_DEBIT_CENTS', amount)
    return positions, amount


def test_exact_three_are_excluded_without_altering_any_ledger_or_snapshot(db, monkeypatch):
    positions, amount = approved(db, monkeypatch)
    original = preserved(db)
    cash = expanded._balance(db)
    changes = db.connection().connection.driver_connection.total_changes
    data = expanded.account_summary(db, now=NOW)
    assert data['trade_pagination']['total'] == 0 and data['trades'] == []
    assert data['data_exclusions']['excluded_count'] == 3
    assert data['research_view']['equity_cents'] == 200000
    assert data['equity_cents'] == 200000-amount
    assert data['realized_cents'] == -amount and data['research_view']['realized_cents'] == 0
    assert data['research_view']['cash_ledger_changed'] is False
    assert data['research_view']['capacity_replayed'] is False
    assert data['research_view']['equity_history']['daily'][-1]['equity_cents'] == 200000
    assert expanded._balance(db) == cash
    assert preserved(db) == original
    assert db.connection().connection.driver_connection.total_changes == changes
    assert all(p.status == 'WRITTEN_OFF' for p in positions)


def test_archive_and_all_views_have_correct_server_side_counts(db, monkeypatch):
    positions, _ = approved(db, monkeypatch)
    ids = {p.id for p in positions}
    for view in ('EXCLUDED', 'ALL'):
        result = expanded.account_summary(db, now=NOW, trade_view=view, page=99)
        assert result['trade_pagination'] == {'page': 1, 'pages': 1, 'total': 3, 'view': view}
        assert {t['id'] for t in result['trades']} == ids
        assert result['data_exclusions']['reason'].startswith('Excluded by operator')
    with pytest.raises(ValueError, match='Unknown paper trade view'):
        expanded.account_summary(db, now=NOW, trade_view='DROP_EVERY_LOSS')


def test_historical_excluded_open_value_is_removed_not_double_counted(db, monkeypatch):
    _, _ = approved(db, monkeypatch)
    data = expanded.account_summary(db, now=NOW)
    history = data['research_view']['equity_history']['intraday']
    opened = next(p for p in history if p['at'].startswith((START+timedelta(seconds=2)).isoformat()))
    assert opened['source_equity_cents'] < 200000
    assert opened['equity_cents'] == 200000  # Not source equity + refunded debit + retained excluded bids.
    at_end = next(p for p in history if p['at'] == END.isoformat())
    assert at_end['source_equity_cents'] is None
    assert at_end['equity_cents'] == 200000
    assert at_end['reconstructed_from_saved_evidence']
    original = db.scalar(select(ForwardPaperEquitySnapshot).where(
        ForwardPaperEquitySnapshot.account_key == expanded.KEY,
        ForwardPaperEquitySnapshot.observed_at == END))
    assert original.equity_cents is None


def test_unrelated_unknown_is_neither_hidden_nor_filled(db, monkeypatch):
    positions, _ = approved(db, monkeypatch, count=4)
    result = expanded.account_summary(db, now=NOW)
    assert result['trade_pagination']['total'] == 1
    assert result['trades'][0]['id'] == positions[-1].id
    assert result['research_view']['equity_cents'] is None
    at_end = next(p for p in result['research_view']['equity_history']['intraday'] if p['at'] == END.isoformat())
    assert at_end['equity_cents'] is None and at_end['unpriced_positions'] == 1


def test_future_writeoff_is_not_automatically_excluded(db, monkeypatch):
    positions, amount = approved(db, monkeypatch, count=4)
    other = positions[-1]
    request = paper_writeoffs.prepare_request(db, symbols=[other.detail['option_symbol']],
        expected_total_cents=other.detail['entry_debit_cents'], approval_ref='separate-future-assumption')
    paper_writeoffs.apply_request(db, request, now=NOW+timedelta(seconds=1))
    db.commit()
    result = expanded.account_summary(db, now=NOW+timedelta(seconds=1))
    assert result['trade_pagination']['total'] == 1 and result['trades'][0]['id'] == other.id
    assert result['research_view']['excluded_debit_cents'] == amount
    assert result['research_view']['included_manual_write_off_count'] == 1
    assert result['research_view']['realized_cents'] == -other.detail['entry_debit_cents']


def test_scope_hash_or_amount_mismatch_never_silently_excludes(db, monkeypatch):
    _, _ = approved(db, monkeypatch)
    monkeypatch.setattr(research, 'EXPECTED_DEBIT_CENTS', 1)
    result = expanded.account_summary(db, now=NOW)
    assert result['data_exclusions']['state'] == 'SCOPE_REQUIRES_REVIEW'
    assert result['research_view'] is None and result['trade_pagination']['total'] == 3
    monkeypatch.setattr(research, 'APPROVAL_REQUEST_SHA256', 'a'*64)
    result = expanded.account_summary(db, now=NOW)
    assert result['data_exclusions']['excluded_count'] == 0


def test_other_account_has_no_exclusion_or_financial_adjustment(db, monkeypatch):
    approved(db, monkeypatch)
    before = preserved(db)
    result = expanded.account_summary(db, now=NOW, account_key='tasty-session-v2-20261019')
    assert 'research_view' not in result
    assert result['equity_cents'] == 200000
    assert preserved(db) == before


def test_missing_snapshot_roster_stays_unknown(db, monkeypatch):
    approved(db, monkeypatch)
    snapshot = db.scalar(select(ForwardPaperEquitySnapshot).where(
        ForwardPaperEquitySnapshot.account_key == expanded.KEY,
        ForwardPaperEquitySnapshot.observed_at == END))
    snapshot.detail = {**snapshot.detail, 'positions': []}
    db.commit()
    result = expanded.account_summary(db, now=NOW)
    at_end = next(p for p in result['research_view']['equity_history']['intraday'] if p['at'] == END.isoformat())
    assert at_end['equity_cents'] is None


def test_future_quote_mutation_cannot_change_past_research_points(db, monkeypatch):
    positions, _ = approved(db, monkeypatch, count=4)
    before = deepcopy(expanded.account_summary(db, now=NOW)['research_view']['equity_history'])
    p = positions[-1]
    p.detail = {**p.detail, 'valuation': {'bid': 999999, 'ask': 999999,
                 'bid_at': (NOW+timedelta(days=1)).isoformat(),
                 'ask_at': (NOW+timedelta(days=1)).isoformat()}}
    db.commit()
    assert expanded.account_summary(db, now=NOW)['research_view']['equity_history'] == before


def test_server_pagination_excludes_before_limiting_and_keeps_all_live_positions(db, monkeypatch):
    positions, _ = approved(db, monkeypatch, count=26)
    excluded = {p.id for p in positions[:3]}
    one = expanded.account_summary(db, now=NOW, page=1)
    two = expanded.account_summary(db, now=NOW, page=2)
    assert one['trade_pagination']['total'] == two['trade_pagination']['total'] == 23
    assert len(one['trades']) == 20 and len(two['trades']) == 3
    assert {p['id'] for p in one['trades']+two['trades']} == {p.id for p in positions}-excluded
    assert len(one['open_trades']) == 0  # Expired unknowns are not presented as live open positions.
    assert one['expired_unresolved_count'] == 7


def test_live_unresolved_position_is_visible_even_outside_the_latest_trade_page(db, monkeypatch):
    positions, _ = approved(db, monkeypatch, count=26)
    p = positions[3]
    mark = db.get(AutomatedOptionMark, p.entry_mark_id)
    mark.expiration += timedelta(days=1)
    p.status = 'UNPRICED'
    db.commit()
    result = expanded.account_summary(db, now=NOW, page=1)
    assert p.id not in {t['id'] for t in result['trades']}
    assert {t['id'] for t in result['open_trades']} == {p.id}


def test_recent_completed_trades_do_not_depend_on_the_current_history_page(db, monkeypatch):
    positions, _ = approved(db, monkeypatch, count=26)
    p = positions[3]
    p.status = 'CLOSED'
    p.detail = {**p.detail, 'exit_at': END.isoformat(), 'sale_cents': 7500, 'exit_fee_cents': 50}
    db.commit()
    result = expanded.account_summary(db, now=NOW, page=1)
    assert p.id not in {t['id'] for t in result['trades']}
    assert result['recent_trades'][0]['id'] == p.id


def test_api_forwards_the_requested_archive_view_without_a_write(monkeypatch):
    from fastapi.testclient import TestClient
    from app.api import routes
    from app.main import app

    calls = []
    def summary(db, **kwargs):
        calls.append(kwargs)
        return {'status': 'READ_ONLY_TEST'}
    monkeypatch.setattr(routes, 'account_summary', summary)
    response = TestClient(app).get('/api/forward-paper-account?page=2&trade_view=EXCLUDED')
    assert response.status_code == 200
    assert calls == [{'page': 2, 'account_key': expanded.KEY, 'trade_view': 'EXCLUDED'}]
