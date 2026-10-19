from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.services import forward_account
from app.db.models import (AutomatedOptionMark, ForwardPaperAccount, ForwardPaperEvent,
                           ForwardPaperPosition, ForwardPaperEquitySnapshot)
from app.services.forward_account import (KEY, account_summary, advance_account, ensure_account,
                                          refresh_account_quotes, settlement_at)
from test_performance import SHADOW_START as START, database, row, shadow_contract

RELEASE_START = forward_account.TRIAL_START

@pytest.fixture(autouse=True)
def trial_fixture_clock(monkeypatch):
    # Exercise the permanent trial using these existing August contract fixtures.
    monkeypatch.setattr(forward_account, "TRIAL_START", START-timedelta(seconds=1))


class Quotes:
    def __init__(self, stamp, *, bid=.40, ask=.45, mode="live", **changes):
        self.mode = mode
        self.quote = shadow_contract(stamp=stamp, bid=bid, ask=ask).model_copy(update={"provider": "tastytrade", **changes})

    def status(self):
        return SimpleNamespace(status="healthy", mode=self.mode)

    def cached_option_chain(self, *_):
        return [self.quote]


def candidate(db, name="first", ticker="SPY", now=START):
    trade = row(signal_id=name, ticker=ticker)
    trade.triggered_at = now
    trade.strategy_version = "parlay-v1-session-v2"
    trade.strategy_snapshot = {"input_evidence": {"input_version": "current-session-v2",
                                               "session_date": now.date().isoformat()}}
    db.add(trade)
    db.flush()
    symbol = f"{ticker}260803C00100000"
    mark = AutomatedOptionMark(signal_id=name, position_key=f"{now.date()}:{ticker}",
        trading_date=now.date(), ticker=ticker, strategy_mode=trade.strategy_mode,
        mark_type="ENTRY", mark_status="QUOTED", event_reason="AUTOMATED_BUY",
        event_at=now, observed_at=now, option_symbol=symbol, normalized_option_symbol=symbol,
        expiration=now.date(), strike=100, right="call", bid=.40, ask=.45,
        selected_price=.45, price_basis="ASK", quote_timestamp=now, bid_timestamp=now, ask_timestamp=now,
        provider="tastytrade", data_mode="live", verification_status="verified",
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
    monkeypatch.setattr(forward_account, "STARTING_CASH", 25000)
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
        point = result["equity_history"]["intraday"][-1]
        assert point["equity_cents"] == 199100
        assert point["return_percent"] == -.45


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
        assert result["trades"][0]["entry_debit_cents"] == 4750
        assert result["trades"][0]["net_proceeds_cents"] == 7350
        assert result["trades"][0]["net_proceeds_cents"]-result["trades"][0]["entry_debit_cents"] == result["realized_cents"]
        assert result["charged_fees_cents"] == 200
        assert result["equity_history"]["intraday"][-1]["return_percent"] == 1.3
        assert result["equity_history"]["baseline_cents"] == 200000
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
        assert result["trades"][0]["status"] == "CLOSED"  # Closed trades remain visible after settlement.
        assert sum(e.kind == "SETTLEMENT" for e in db.scalars(select(ForwardPaperEvent))) == 1
        assert result["equity_history"]["daily"][-1]["return_percent"] == 1.3  # Settlement is not profit.


def test_equity_history_keeps_unknown_gaps_and_reads_never_backfill_or_change_cash():
    with database()() as db:
        opened(db)
        before_events = [(e.id, e.settled_cents, e.unsettled_cents) for e in db.scalars(select(ForwardPaperEvent))]
        later = START+timedelta(minutes=2)
        advance_account(db, Quotes(START), now=later)  # Stale quote, still held.
        advance_account(db, Quotes(START), now=later)  # Idempotent observation.
        history = account_summary(db, now=later)["equity_history"]
        assert history["intraday"][-1]["equity_cents"] is None
        assert history["intraday"][-1]["return_percent"] is None
        assert history["intraday"][-1]["unpriced_positions"] == 1
        assert sum(p["at"] == later.isoformat() for p in history["intraday"]) == 1
        count = db.scalar(select(func.count()).select_from(ForwardPaperEquitySnapshot))
        account_summary(db, now=later+timedelta(days=1))
        assert db.scalar(select(func.count()).select_from(ForwardPaperEquitySnapshot)) == count
        assert before_events == [(e.id, e.settled_cents, e.unsettled_cents) for e in db.scalars(select(ForwardPaperEvent))]
        advance_account(db, Quotes(later+timedelta(seconds=2), bid=.60, ask=.65), now=later+timedelta(seconds=2))
        repaired = account_summary(db, now=later+timedelta(seconds=2))["equity_history"]["intraday"]
        assert repaired[-2]["equity_cents"] is None  # Never overwrite a missing past mark.
        assert repaired[-1]["equity_cents"] is not None


def test_existing_account_get_does_not_backfill_beyond_its_initial_funding_observation():
    with database()() as db:
        ensure_account(db, START)
        db.commit()
        result = account_summary(db, now=START+timedelta(days=2))
        assert result["equity_history"]["started_at"] == START.isoformat()
        assert len(result["equity_history"]["daily"]) == 1
        assert result["equity_history"]["daily"][0]["return_percent"] == 0
        assert result["equity_cents"] == 200000


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
    monkeypatch.setattr(forward_account, "STARTING_CASH", 48)
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
    monkeypatch.setattr(forward_account, "STARTING_CASH", cash)
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
    monkeypatch.setattr(forward_account, "STARTING_CASH", 48)
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


def test_trial_waits_until_monday_and_starts_at_actual_processing_not_backdated(monkeypatch):
    monkeypatch.setattr(forward_account, "TRIAL_START", RELEASE_START)
    assert RELEASE_START.isoformat() == "2026-10-19T13:30:00+00:00"
    with database()() as db:
        before = RELEASE_START-timedelta(seconds=1)
        assert ensure_account(db, before) is None
        advance_account(db, now=before)
        scheduled = account_summary(db, now=before)
        assert scheduled["status"] == "SCHEDULED" and scheduled["starting_cash_cents"] == 200000
        assert db.scalar(select(func.count()).select_from(ForwardPaperAccount)) == 0
        # A delayed deployment cannot pretend it traded Monday's opening hours.
        actual = RELEASE_START+timedelta(hours=2)
        candidate(db, now=RELEASE_START)
        advance_account(db, now=actual)
        db.commit()
        summary = account_summary(db, now=actual)
        assert summary["activated_at"] == actual.isoformat()
        assert summary["positions"] == [] and summary["settled_cents"] == 200000
        assert summary["equity_history"]["daily"][0]["return_percent"] == 0
        assert summary["equity_history"]["started_at"] == actual.isoformat()
        advance_account(db, now=actual+timedelta(days=1))
        assert db.scalar(select(func.count()).select_from(ForwardPaperEvent).where(
            ForwardPaperEvent.kind == "FUNDING")) == 1


def test_archived_account_exposure_balances_and_events_are_never_rewritten_or_imported():
    with database()() as db:
        current = ensure_account(db, START-timedelta(seconds=1))
        assert current is not None
        trade = candidate(db, "legacy-position")
        legacy = ForwardPaperAccount(key=forward_account.LEGACY_KEY,
            activated_at=START-timedelta(days=2), processed_at=START-timedelta(days=1),
            mark_watermark=1, revision=8, policy={**current.policy, "version": "forward-cash-v1",
                                               "starting_cash_cents": 2500000})
        db.add(legacy)
        db.flush()
        db.add(ForwardPaperEvent(account_key=legacy.key, event_key="funding", kind="FUNDING",
            occurred_at=legacy.activated_at, settled_cents=2500000, unsettled_cents=0,
            fee_cents=0, realized_cents=0, detail={"original": True}))
        db.add(ForwardPaperEvent(account_key=legacy.key, event_key="entry", kind="ENTRY",
            occurred_at=legacy.processed_at, settled_cents=-4750, unsettled_cents=0,
            fee_cents=150, realized_cents=0, detail={"original": True}))
        db.add(ForwardPaperPosition(account_key=legacy.key, signal_id=trade.signal_id,
            entry_mark_id=1, status="UNPRICED", first_seen_at=legacy.processed_at,
            detail={"ticker": "SPY", "option_symbol": "SPY260803C00100000",
                    "entry_debit_cents": 4750, "entry_fee_cents": 150}))
        db.commit()

        def original_rows():
            result = []
            for model in (ForwardPaperAccount, ForwardPaperEvent, ForwardPaperPosition, ForwardPaperEquitySnapshot):
                key = model.key if model is ForwardPaperAccount else model.account_key
                result.extend([dict(row) for row in db.execute(select(*model.__table__.c).where(
                    key == legacy.key)).mappings()])
            return json.dumps(result, sort_keys=True, default=str)

        before = original_rows()
        # New trial ignores all evidence predating its actual activation; this
        # fixture mark has old input/creation time, even if seen after activation.
        mark = db.get(AutomatedOptionMark, 1)
        mark.created_at = START-timedelta(days=1)
        advance_account(db, Quotes(START), now=START)
        advance_account(db, now=START+timedelta(days=1))
        db.commit()
        result = account_summary(db, now=START+timedelta(days=1))
        archive = account_summary(db, account_key=legacy.key, now=START+timedelta(days=1))
        assert result["settled_cents"] == 200000 and result["positions"] == []
        assert result["equity_history"]["baseline_cents"] == 200000
        assert archive["status"] == "ARCHIVED" and not archive["processing_stale"]
        assert archive["settled_cents"] == 2495250 and archive["equity_cents"] is None
        assert archive["unpriced_debit_cents"] == 4750
        assert archive["positions"][0]["status"] == "UNPRICED"
        assert archive["equity_history"]["daily"] == []
        assert archive["equity_history"]["baseline_cents"] == 2500000
        assert before == original_rows()
        assert [item["key"] for item in result["accounts"]] == [KEY, legacy.key]
        assert not db.new and not db.dirty
        with pytest.raises(ValueError, match="Unknown paper"):
            account_summary(db, account_key="does-not-exist")


@pytest.mark.parametrize("fault", ["provider", "mode", "strategy_version", "input_version", "session_date", "absent_evidence"])
def test_trial_cannot_mix_other_providers_or_legacy_session_inputs(fault):
    with database()() as db:
        ensure_account(db, START-timedelta(seconds=1))
        trade = candidate(db)
        mark = db.scalar(select(AutomatedOptionMark))
        if fault == "provider":
            mark.provider = "tradier"
        elif fault == "mode":
            mark.data_mode = "delayed"
        elif fault == "strategy_version":
            trade.strategy_version = "unrelated-new-strategy"
        elif fault == "absent_evidence":
            trade.strategy_snapshot = {}
        else:
            evidence = {**trade.strategy_snapshot["input_evidence"],
                        fault: "old" if fault == "input_version" else "2026-08-02"}
            trade.strategy_snapshot = {"input_evidence": evidence}
        advance_account(db, Quotes(START), now=START)
        advance_account(db, Quotes(START+timedelta(seconds=2)), now=START+timedelta(seconds=2))
        result = account_summary(db, now=START+timedelta(seconds=2))
        assert result["settled_cents"] == 200000
        skipped = db.scalar(select(ForwardPaperPosition))
        assert skipped.status == "SKIPPED" and "Outside corrected Tastytrade trial" in skipped.detail["reason"]


def test_tasty_trial_does_not_fill_from_a_tradier_refresh():
    with database()() as db:
        ensure_account(db, START-timedelta(seconds=1))
        candidate(db)
        advance_account(db, now=START)
        later = START+timedelta(seconds=2)
        advance_account(db, Quotes(later, provider="tradier"), now=later)
        assert account_summary(db, now=later)["settled_cents"] == 200000
        assert db.scalar(select(ForwardPaperPosition)).status == "PENDING_ENTRY"
