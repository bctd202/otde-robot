from datetime import timedelta
from types import SimpleNamespace

import pytest

from sqlalchemy import select

from app.api.routes import performance
from app.db.models import AutomatedOptionMark, AutomatedOptionObservation, LotteryQuoteSnapshot
from app.services.performance import execution_cost_analysis, link_paper_position, paper_portfolio_results
from app.services.option_research import (option_path_research, record_option_observations,
                                          research_definition)
from app.services.lottery_tracker import _cash_portfolio, _exit_scenario, track_lottery_scan, tracker_points
from test_performance import (SHADOW_START, ShadowProvider, add_shadow_pair, database,
                              row, shadow_contract)
from test_lottery_tracker import LiveLotteryProvider


def test_journaling_never_removes_original_automatic_buy_or_uses_manual_pnl():
    with database()() as db:
        first = row(signal_id="first")
        first.dedupe_key = "ONE_MIN_0DTE:SPY:call:first"
        second = row(signal_id="later"); second.triggered_at += timedelta(minutes=10)
        db.add(first); db.commit()
        link_paper_position(db, SimpleNamespace(symbol="SPY", direction="call", strategy_mode="ONE_MIN_0DTE", id=123))
        assert first.user_entered is False and first.paper_position_id == 123
        db.add(second); db.commit()
        first.user_entered = True  # Legacy journal behavior is recognized without a migration rewrite.
        db.commit()
        payload = performance(db=db)
        assert payload["signals"][0]["signal_id"] == "first"
        assert payload["signals"][0]["return_basis"] == "UNDERLYING"
        assert payload["selection_integrity"]["legacy_linked_rows_included"] == 1
        assert first.user_entered is True
        assert performance(user_entered=True, db=db)["signals"][0]["signal_id"] == "first"


def test_cash_cannot_spend_exit_proceeds_before_quote_observation():
    with database()() as db:
        first, second = row(signal_id="first"), row(signal_id="later", ticker="QQQ")
        add_shadow_pair(db, first, entry_ask=.45, exit_bid=.90, offset_minutes=0)
        add_shadow_pair(db, second, entry_ask=.80, exit_bid=.90, offset_minutes=10)
        db.flush()
        exit_mark = db.scalar(select(AutomatedOptionMark).where(
            AutomatedOptionMark.signal_id == first.signal_id, AutomatedOptionMark.mark_type == "EXIT"))
        exit_mark.observed_at = SHADOW_START+timedelta(minutes=20)
        db.commit()
        result = paper_portfolio_results(db, [first, second], 100)["portfolios"][0]
        assert result["positions_taken"] == 1
        assert result["skipped_insufficient_cash"] == 1
        assert result["cash_available_dollars"] == 145


def test_missing_exit_remains_unknown_with_explicit_zero_value_sensitivity():
    with database()() as db:
        trade = row(); add_shadow_pair(db, trade, entry_ask=.45, exit_bid=.90, offset_minutes=0)
        db.flush()
        exit_mark = db.scalar(select(AutomatedOptionMark).where(AutomatedOptionMark.mark_type == "EXIT"))
        exit_mark.mark_status = "OPTION_QUOTE_GAP"; exit_mark.selected_price = None
        db.commit()
        result = paper_portfolio_results(db, [trade], 100)["portfolios"][0]
        assert result["realized_pnl_dollars"] == 0
        assert result["cash_available_dollars"] == 55
        assert result["book_equity_dollars"] == 100
        assert result["unpriced_exit_cost_dollars"] == 45
        assert result["active_capital_at_cost_dollars"] == 0
        assert result["equity_excluding_unpriced_exits_dollars"] == 55
        assert result["daily"][-1]["equity_excluding_unpriced_exits_dollars"] == 55
        assert result["liquidation_value_dollars"] is None
        assert exit_mark.selected_price is None


def lotto(wave, minute, exit_minute, cost=40, value=80, status="CLOSED"):
    return {"entry_wave_id": wave, "option_symbol": wave, "first_seen_at": SHADOW_START+timedelta(minutes=minute),
            "trading_date": SHADOW_START.date(), "entry_cost": cost, "setup_score": 80, "status": status,
            "exit_scenarios": {"take_2x": {"exit_at": SHADOW_START+timedelta(minutes=exit_minute)
                                           if exit_minute is not None else None,
                                           "exit_value": value, "target_hit": value is not None and value>=2*cost}}}


def test_lotto_overlapping_trades_do_not_recycle_future_cash():
    result = _cash_portfolio([lotto("first",0,20),lotto("second",5,30)], "take_2x", "test", 50, 100)
    assert result["positions_taken"] == 1 and result["skipped_insufficient_cash"] == 1
    assert result["cash_available"] == 90
    assert result["daily"][-1]["daily_realized_pnl"] == 40


def test_lotto_target_closes_active_tracker_and_missing_exit_stays_unpriced():
    result = _cash_portfolio([lotto("target",0,2,status="ACTIVE"),
                              lotto("gap",3,None,value=None)], "take_2x", "test", 100, 100, fixed_cost=1)
    assert result["closed_positions"] == 1
    assert result["active_positions"] == 0
    assert result["unpriced_positions"] == 1 and result["unpriced_cost"] == 40
    assert result["cash_available"] == 98 and result["book_equity"] == 138
    assert result["pnl"] == 38


class CachedProvider(ShadowProvider):
    def cached_option_chain(self, ticker, expiration):
        return [self.exit_contract] if self.exit_contract is not None else None


def entry_for_research(db, *, legacy=False):
    trade = row()
    add_shadow_pair(db, trade, entry_ask=.45, exit_bid=.90, offset_minutes=0)
    db.flush()
    db.delete(db.scalar(select(AutomatedOptionMark).where(AutomatedOptionMark.mark_type == "EXIT")))
    trade.exit_reason = "OPEN"; trade.result_r = None; trade.exit_at = None
    trade.strategy_snapshot = {} if legacy else {"option_research": research_definition()}
    db.commit()
    return trade


def test_observations_are_cache_only_idempotent_and_fresh_across_restart():
    local = database(); now = SHADOW_START+timedelta(minutes=3)
    provider = CachedProvider(); provider.exit_contract = shadow_contract(stamp=now, bid=0, ask=.01)
    with local() as db:
        entry_for_research(db)
        record_option_observations(db, provider, now=now)
        db.commit()
    with local() as db:
        record_option_observations(db, provider, now=now+timedelta(seconds=5))
        record_option_observations(db, provider, now=now+timedelta(minutes=2))
        db.commit()
        points = list(db.scalars(select(AutomatedOptionObservation).order_by(AutomatedOptionObservation.id)))
        assert [p.status for p in points] == ["QUOTED", "GAP"]
        assert points[0].bid == 0 and points[1].bid is None
        assert provider.chain_calls == 0


def test_observations_do_not_backfill_old_cohort_or_sample_off_hours():
    with database()() as db:
        trade = entry_for_research(db, legacy=True)
        provider = CachedProvider()
        record_option_observations(db, provider, now=SHADOW_START)
        trade.strategy_snapshot = {"option_research": research_definition()}
        record_option_observations(db, provider, now=SHADOW_START.replace(hour=22))
        assert list(db.scalars(select(AutomatedOptionObservation))) == []
        assert provider.chain_calls == 0


def test_maximum_hold_compares_only_matching_forward_quotes_and_preserves_baseline():
    with database()() as db:
        trade = row()
        add_shadow_pair(db, trade, entry_ask=.45, exit_bid=.10, offset_minutes=0)
        trade.strategy_snapshot = {"option_research": research_definition()}
        db.flush()
        baseline = db.scalar(select(AutomatedOptionMark).where(AutomatedOptionMark.mark_type == "EXIT"))
        baseline.observed_at = baseline.event_at = SHADOW_START+timedelta(minutes=45)
        t = SHADOW_START+timedelta(minutes=15,seconds=5)
        db.add(AutomatedOptionObservation(signal_id=trade.signal_id, minute_at=t.replace(second=0),
            observed_at=t, option_symbol="SPY260803C00100000", status="QUOTED", reason="test",
            bid=.60, ask=.65, bid_timestamp=t, ask_timestamp=t, provider="tradier", cohort="test"))
        db.commit()
        result = option_path_research(db, [trade])
        short, missing, early = result["scenarios"]
        assert short["matched_plays"] == 1 and short["alternative_net_dollars"] == 14
        assert short["baseline_net_dollars"] == -36 and short["difference_dollars"] == 50
        assert missing["matched_plays"] == 0 and missing["incomplete_plays"] == 1
        assert early["matched_plays"] == 1 and early["difference_dollars"] == 0
        assert baseline.selected_price == .10 and trade.result_r == -1
        trade.strategy_snapshot = {"option_research": {**research_definition(), "code_fingerprint": "older"}}
        assert all(s["matched_plays"] == 0 for s in option_path_research(db, [trade])["scenarios"])


@pytest.mark.parametrize("change", ["future", "wrong_contract", "delayed", "nan"])
def test_invalid_observations_are_gaps_not_prices(change):
    now = SHADOW_START+timedelta(minutes=3)
    with database()() as db:
        entry_for_research(db)
        provider = CachedProvider(); provider.exit_contract = shadow_contract(stamp=now)
        if change == "future":
            provider.exit_contract.bid_timestamp = now+timedelta(seconds=1)
        elif change == "wrong_contract":
            provider.exit_contract.option_symbol = "SPY260803C00101000"
        elif change == "delayed":
            provider.exit_contract.data_mode = "delayed"
        else:
            provider.exit_contract.bid = float("nan")
        record_option_observations(db, provider, now=now)
        point = db.scalar(select(AutomatedOptionObservation))
        assert point.status == "GAP" and point.bid is None
        assert provider.chain_calls == 0


def test_exact_lotto_target_does_not_capture_quote_jump_overshoot():
    t = SHADOW_START+timedelta(minutes=2)
    point = LotteryQuoteSnapshot(observed_at=t, quote_timestamp=t, bid_timestamp=t, bid=.9)
    observed = _exit_scenario([point], .2, "CLOSED", 2)
    capped = _exit_scenario([point], .2, "CLOSED", 2, cap_target=True)
    assert observed["exit_value"] == 90 and capped["exit_value"] == 40
    assert capped["exit_at"] == observed["exit_at"] == t
    assert point.bid == .9


def test_closing_one_lotto_position_keeps_other_open_debits_in_book_equity():
    result = _cash_portfolio([lotto("first",0,3), lotto("open",1,None,value=None,status="ACTIVE")],
                             "take_2x", "test", 100, 100)
    assert result["cash_available"] == 100 and result["book_equity"] == 140
    assert result["active_positions"] == 1 and result["closed_positions"] == 1


def test_cost_outcome_counts_are_exclusive_at_float_roundoff_breakeven():
    trade = row()
    result = execution_cost_analysis([trade], {trade.signal_id:{"status":"CLOSED",
        "entry_ask":.20, "exit_bid":.21, "contract_multiplier":100}})
    net = result["net_after_costs"]
    assert net["pnl_dollars"] == 0
    assert net["wins"] == net["losses"] == 0
    assert net["breakeven"] == result["closed_with_quote"] == 1


def test_lotto_uses_wall_clock_freshness_even_when_provider_clock_is_stale():
    provider = LiveLotteryProvider()
    with database()() as db:
        tracked = track_lottery_scan(db, provider, ["SPY"], provider.now-timedelta(minutes=1), now=provider.now)
        assert len(tracker_points(db, tracked[0].id)) == 1
        # Same stale provider quote must not turn into a fresh observation on a later scan.
        track_lottery_scan(db, provider, ["SPY"], provider.now, now=provider.now+timedelta(minutes=4))
        assert len(tracker_points(db, tracked[0].id)) == 1


def test_forward_definition_does_not_include_credentials():
    definition = research_definition()
    assert set(definition["configuration"]) == {"provider", "configured_universe", "flex_limit",
        "option_shadow_enabled", "exit_quote_lag_seconds", "scan_second"}
