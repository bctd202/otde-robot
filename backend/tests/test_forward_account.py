from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.models import (AutomatedOptionMark, ForwardPaperAccount, ForwardPaperEvent,
                           ForwardPaperPosition)
from app.services.forward_account import (KEY, account_summary, advance_account, ensure_account,
                                          refresh_account_quotes, settlement_at)
from test_performance import SHADOW_START as START, database, row, shadow_contract


class Quotes:
    def __init__(self, stamp, *, bid=.40, ask=.45, mode="live", **changes):
        self.mode = mode
        self.quote = shadow_contract(stamp=stamp, bid=bid, ask=ask).model_copy(update=changes)

    def status(self):
        return SimpleNamespace(status="healthy", mode=self.mode)

    def cached_option_chain(self, *_):
        return [self.quote]


def candidate(db, name="first", ticker="SPY", now=START):
    trade = row(signal_id=name, ticker=ticker)
    trade.triggered_at = now
    db.add(trade)
    db.flush()
    symbol = f"{ticker}260803C00100000"
    mark = AutomatedOptionMark(signal_id=name, position_key=f"{now.date()}:{ticker}",
        trading_date=now.date(), ticker=ticker, strategy_mode=trade.strategy_mode,
        mark_type="ENTRY", mark_status="QUOTED", event_reason="AUTOMATED_BUY",
        event_at=now, observed_at=now, option_symbol=symbol, normalized_option_symbol=symbol,
        expiration=now.date(), strike=100, right="call", bid=.40, ask=.45,
        selected_price=.45, price_basis="ASK", quote_timestamp=now, bid_timestamp=now, ask_timestamp=now,
        provider="tradier", data_mode="live", verification_status="verified",
        verification_reason="test", contract_multiplier=100, created_at=now)
    db.add(mark)
    db.flush()
    return trade


def opened(db):
    ensure_account(db, START-timedelta(seconds=1))
    trade = candidate(db)
    advance_account(db, Quotes(START), now=START)
    advance_account(db, Quotes(START+timedelta(seconds=2)), now=START+timedelta(seconds=2))
    db.commit()
    return trade


def test_read_does_not_activate_and_restart_does_not_import_history_or_reset_policy(monkeypatch):
    local = database()
    with local() as db:
        assert account_summary(db)["status"] == "NOT_STARTED"
        candidate(db)
        ensure_account(db, START+timedelta(seconds=1))
        db.commit()
    monkeypatch.setattr(get_settings(), "paper_money_starting_cash", 25000)
    with local() as db:
        advance_account(db, Quotes(START+timedelta(seconds=2)), now=START+timedelta(seconds=2))
        db.commit()
        result = account_summary(db)
        assert result["policy"]["starting_cash_cents"] == 200000
        assert result["settled_cents"] == 200000
        assert result["positions"] == []
        assert len(result["events"]) == 1


def test_new_entry_requires_later_quote_and_reserves_exit_fee():
    with database()() as db:
        ensure_account(db, START-timedelta(seconds=1))
        candidate(db)
        advance_account(db, Quotes(START), now=START)
        result = account_summary(db, now=START)
        assert result["positions"][0]["status"] == "PENDING_ENTRY"
        assert result["settled_cents"] == 200000
        advance_account(db, Quotes(START+timedelta(seconds=2)), now=START+timedelta(seconds=2))
        result = account_summary(db, now=START+timedelta(seconds=2))
        assert result["settled_cents"] == 195250  # $46 option + $1.50 opening costs
        assert result["available_cents"] == 195200
        assert result["equity_cents"] == 199100  # $39 liquidation less $0.50 closing costs
        assert result["realized_cents"] == 0
        assert result["charged_fees_cents"] == 150


def test_exact_cash_flow_exit_settlement_restart_and_underlying_unchanged():
    local = database()
    with local() as db:
        trade = opened(db)
        trade.exit_reason = "TARGET"
        trade.exit_at = START+timedelta(minutes=5)
        trade.result_r = 1.5
        decision = START+timedelta(minutes=5)
        advance_account(db, Quotes(decision, bid=.75, ask=.80), now=decision)
        assert account_summary(db)["positions"][0]["status"] == "OPEN"
        fill = decision+timedelta(seconds=2)
        advance_account(db, Quotes(fill, bid=.75, ask=.80), now=fill)
        advance_account(db, Quotes(fill, bid=.75, ask=.80), now=fill)
        result = account_summary(db, now=fill)
        assert result["settled_cents"] == 195200
        assert result["unsettled_cents"] == 7400
        assert result["realized_cents"] == 2600
        assert result["equity_cents"] == 202600
        assert result["charged_fees_cents"] == 200
        assert trade.result_r == 1.5 and trade.entry_price == 100 and trade.target_price == 101.5
        assert sum(e.kind == "EXIT" for e in db.scalars(select(ForwardPaperEvent))) == 1
        db.commit()
    with local() as db:
        due = datetime(2026, 8, 4, 13, 30, tzinfo=timezone.utc)
        advance_account(db, now=due-timedelta(seconds=1))
        assert account_summary(db)["unsettled_cents"] == 7400
        advance_account(db, now=due)
        advance_account(db, now=due)
        result = account_summary(db, now=due)
        assert result["settled_cents"] == result["equity_cents"] == 202600
        assert result["unsettled_cents"] == 0
        assert result["positions"] == []
        assert result["realized_cents"] == 2600
        assert sum(e.kind == "SETTLEMENT" for e in db.scalars(select(ForwardPaperEvent))) == 1


@pytest.mark.parametrize("changes", [
    {"stamp": START}, {"stamp": START+timedelta(minutes=3)},
    {"mode": "delayed"}, {"data_mode": "demo"}, {"provider": "unapproved"},
    {"symbol": "QQQ"}, {"option_symbol": "SPY260803P00100000"},
    {"strike": 101}, {"bid": float("nan")}, {"ask": float("inf")},
    {"bid_timestamp": None}, {"ask_timestamp": None},
])
def test_entry_rejects_unusable_or_predecision_quotes(changes):
    with database()() as db:
        ensure_account(db, START-timedelta(seconds=1))
        candidate(db)
        advance_account(db, now=START)
        arguments = {"stamp": START+timedelta(seconds=2), **changes}
        advance_account(db, Quotes(**arguments), now=START+timedelta(seconds=2))
        assert account_summary(db)["settled_cents"] == 200000
        advance_account(db, now=START+timedelta(seconds=121))
        assert db.scalar(select(ForwardPaperPosition)).status == "SKIPPED"


@pytest.mark.parametrize("cause", ["deadline", "expiry", "underlying_gap"])
def test_missing_exits_keep_debit_and_unknown_equity(cause):
    with database()() as db:
        trade = opened(db)
        if cause == "underlying_gap":
            trade.exit_reason = "DATA_GAP"
            now = START+timedelta(minutes=1)
        elif cause == "expiry":
            now = START.replace(hour=20, minute=0)
        else:
            trade.exit_reason = "TARGET"
            trade.exit_at = START+timedelta(minutes=1)
            advance_account(db, now=trade.exit_at)
            now = trade.exit_at+timedelta(seconds=181)
        advance_account(db, now=now)
        advance_account(db, now=now+timedelta(seconds=1))
        result = account_summary(db, now=now)
        assert result["settled_cents"] == 195250 and result["unsettled_cents"] == 0
        assert result["unpriced_positions"] == 1 and result["unpriced_debit_cents"] == 4750
        assert result["equity_cents"] is None and result["realized_cents"] == 0
        assert result["positions"][0]["status"] == "UNPRICED"
        assert sum(e.kind == "QUOTE_GAP" for e in db.scalars(select(ForwardPaperEvent))) == 1


def test_stale_open_marks_hide_equity_without_closing_position():
    with database()() as db:
        opened(db)
        result = account_summary(db, now=START+timedelta(seconds=63))
        assert result["equity_cents"] is None
        assert result["positions"][0]["status"] == "OPEN"


def test_zero_bid_is_explicit_evidence_and_can_pay_reserved_fee(monkeypatch):
    monkeypatch.setattr(get_settings(), "paper_money_starting_cash", 48)
    with database()() as db:
        trade = opened(db)
        trade.exit_reason = "STOP"
        trade.exit_at = START+timedelta(minutes=1)
        advance_account(db, now=trade.exit_at)
        now = trade.exit_at+timedelta(seconds=2)
        advance_account(db, Quotes(now, bid=0, ask=.01), now=now)
        result = account_summary(db, now=now)
        assert result["realized_cents"] == -4800
        assert result["settled_cents"] == result["unsettled_cents"] == result["equity_cents"] == 0


@pytest.mark.parametrize("cash,ask,reason", [(47.99, .45, "Insufficient"), (2000, .99, "budget"), (2000, .8, "spread")])
def test_budget_cash_and_spread_rejections(monkeypatch, cash, ask, reason):
    monkeypatch.setattr(get_settings(), "paper_money_starting_cash", cash)
    with database()() as db:
        ensure_account(db, START-timedelta(seconds=1)); candidate(db)
        advance_account(db, now=START)
        now = START+timedelta(seconds=2)
        bid = .94 if ask == .99 else .40
        advance_account(db, Quotes(now, ask=ask, bid=bid), now=now)
        position = db.scalar(select(ForwardPaperPosition))
        assert position.status == "SKIPPED" and reason in position.detail["reason"]
        assert account_summary(db)["settled_cents"] == round(cash*100)


def test_closed_before_entry_is_skipped_and_no_hindsight_fill():
    with database()() as db:
        ensure_account(db, START-timedelta(seconds=1)); trade = candidate(db)
        advance_account(db, now=START)
        trade.exit_reason = "TARGET"
        advance_account(db, Quotes(START+timedelta(seconds=2)), now=START+timedelta(seconds=2))
        assert db.scalar(select(ForwardPaperPosition)).status == "SKIPPED"
        assert account_summary(db)["settled_cents"] == 200000


def test_concurrent_limit_includes_unpriced_positions():
    with database()() as db:
        opened(db)
        account = db.get(ForwardPaperAccount, KEY)
        # Isolated fixture policy: production policy has no mutation endpoint.
        account.policy = {**account.policy, "max_positions": 1}
        first = db.scalar(select(ForwardPaperPosition))
        first.status = "UNPRICED"
        candidate(db, "second", "QQQ", START+timedelta(seconds=10))
        advance_account(db, now=START+timedelta(seconds=10))
        second = db.scalar(select(ForwardPaperPosition).where(ForwardPaperPosition.signal_id == "second"))
        assert second.status == "SKIPPED" and "Concurrent" in second.detail["reason"]


@pytest.mark.parametrize("day,expected", [
    ("2026-10-09", "2026-10-13"), ("2026-11-10", "2026-11-12"),
    ("2026-11-25", "2026-11-27"), ("2026-12-24", "2026-12-28"),
    ("2026-08-03", "2026-08-04"), ("2028-12-29", None),
])
def test_settlement_bank_holidays_weekends_and_unknown_calendar(day, expected):
    due = settlement_at(datetime.fromisoformat(f"{day}T15:00:00+00:00"))
    assert (due.date().isoformat() if due else None) == expected


def test_atomic_rollback_prevents_partial_cash_and_duplicate_entries():
    local = database()
    with local() as db:
        ensure_account(db, START-timedelta(seconds=1)); candidate(db)
        advance_account(db, now=START); db.commit()
        advance_account(db, Quotes(START+timedelta(seconds=2)), now=START+timedelta(seconds=2))
        db.rollback()
    with local() as db:
        assert account_summary(db)["settled_cents"] == 200000
        advance_account(db, Quotes(START+timedelta(seconds=2)), now=START+timedelta(seconds=2))
        db.commit()
        assert account_summary(db)["settled_cents"] == 195250
        assert db.scalar(select(func.count()).select_from(ForwardPaperEvent)) == 2


def test_ledger_pagination_and_get_are_read_only():
    with database()() as db:
        ensure_account(db, START)
        for index in range(25):
            db.add(ForwardPaperEvent(account_key=KEY, event_key=f"test:{index}", occurred_at=START,
                kind="SKIP", settled_cents=0, unsettled_cents=0, fee_cents=0, realized_cents=0, detail={}))
        db.commit()
        first = account_summary(db, page=1)
        second = account_summary(db, page=2)
        assert len(first["events"]) == 20 and len(second["events"]) == 6
        assert not {e["id"] for e in first["events"]} & {e["id"] for e in second["events"]}
        assert not db.new and not db.dirty


def test_unsettled_sale_cannot_fund_another_entry(monkeypatch):
    monkeypatch.setattr(get_settings(), "paper_money_starting_cash", 48)
    with database()() as db:
        trade = opened(db)
        trade.exit_reason = "TARGET"
        trade.exit_at = START+timedelta(minutes=1)
        advance_account(db, now=trade.exit_at)
        now = trade.exit_at+timedelta(seconds=2)
        advance_account(db, Quotes(now, bid=.75, ask=.80), now=now)
        candidate(db, "second", "QQQ", now)
        advance_account(db, now=now)
        now += timedelta(seconds=2)
        advance_account(db, Quotes(now, symbol="QQQ", option_symbol="QQQ260803C00100000"), now=now)
        second = db.scalar(select(ForwardPaperPosition).where(ForwardPaperPosition.signal_id == "second"))
        assert second.status == "SKIPPED" and "Insufficient" in second.detail["reason"]
        assert account_summary(db, now=now)["unsettled_cents"] == 7400


def test_restart_does_not_fill_an_old_exit_at_a_new_favorable_price():
    with database()() as db:
        trade = opened(db)
        trade.exit_reason = "STOP"
        trade.exit_at = START+timedelta(minutes=1)
        now = START+timedelta(hours=1)
        advance_account(db, Quotes(now, bid=5, ask=5.05), now=now)
        result = account_summary(db, now=now)
        assert result["realized_cents"] == 0 and result["unsettled_cents"] == 0
        assert result["positions"][0]["status"] == "UNPRICED"


def test_structured_contract_does_not_silently_carry_overnight():
    with database()() as db:
        opened(db)
        mark = db.scalar(select(AutomatedOptionMark))
        mark.expiration += timedelta(days=10)
        advance_account(db, now=START.replace(hour=20, minute=0))
        assert db.scalar(select(ForwardPaperPosition)).status == "UNPRICED"


def test_processing_staleness_and_backwards_clock():
    with database()() as db:
        opened(db)
        advance_account(db, now=START-timedelta(days=1))
        assert account_summary(db, now=START+timedelta(minutes=5))["processing_stale"] is True
        assert account_summary(db, now=START+timedelta(seconds=3))["processing_stale"] is False
        assert account_summary(db)["settled_cents"] == 195250


@pytest.mark.parametrize("remaining,mode,hour,expected", [(100,"live",14,6),(20,"live",14,0),(21,"live",14,1),(100,"delayed",14,0),(100,"live",21,0)])
def test_quote_refresh_is_bounded_live_only_and_preserves_reserve(remaining, mode, hour, expected):
    class Provider:
        def status(self): return SimpleNamespace(status="healthy", mode=mode)
        def cached_option_chain(self, *_): return None
        def budget_status(self): return {"remaining": remaining-self.calls}
        def option_chain(self, *_): self.calls += 1
        calls = 0
    with database()() as db:
        ensure_account(db, START-timedelta(seconds=1))
        for index in range(8):
            candidate(db, str(index), f"T{index}")
        provider = Provider()
        assert refresh_account_quotes(db, provider, now=START.replace(hour=hour)) == expected
        assert provider.calls == expected


def test_quote_refresh_keeps_post_signal_exit_observable():
    class Provider(Quotes):
        def cached_option_chain(self, *_): return [self.quote] if self.fetched else None
        def option_chain(self, *_): self.fetched = True; return [self.quote]
        fetched = False
    with database()() as db:
        trade = opened(db)
        trade.exit_reason = "STOP"
        trade.exit_at = START+timedelta(minutes=1)
        advance_account(db, now=trade.exit_at)
        now = trade.exit_at+timedelta(seconds=2)
        provider = Provider(now)
        assert refresh_account_quotes(db, provider, now=now) == 1
        advance_account(db, provider, now=now)
        assert account_summary(db, now=now)["positions"][0]["status"] == "UNSETTLED"
