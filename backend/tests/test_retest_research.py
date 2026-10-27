from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import pytest

from app.schemas.market import CandleOut, OptionContractOut
from app.services.retest_evaluation import evaluation_sessions, paired_block_bootstrap
from app.services.retest_research import FrozenSetup, TimingState, advance, canonical, start

BASE = datetime(2026, 10, 27, 14, 0, tzinfo=timezone.utc)


def quote(at, direction="call", **changes):
    value = OptionContractOut(symbol="SPY", option_symbol=f"SPY261027{'C' if direction == 'call' else 'P'}00100000",
        expiration=BASE.date(), strike=100, right=direction, bid=.45, ask=.48, last=.47,
        volume=1000, open_interest=1000, timestamp=at, bid_timestamp=at, ask_timestamp=at,
        received_at=at, receipt_basis="REST_RESPONSE_RECEIVED_V1", provider="tastytrade", data_mode="live")
    return value.model_copy(update=changes)


def setup(direction="call", **changes):
    value = FrozenSetup(ticker="SPY", direction=direction, breakout_at=BASE,
        observed_at=BASE+timedelta(minutes=1, seconds=5), breakout=100,
        stop=99 if direction == "call" else 101, target=103 if direction == "call" else 97,
        planning_risk=2, entry_low=.4, entry_high=.5, no_chase=.6,
        entry_cutoff=BASE.replace(hour=19, minute=45), timed_exit=BASE.replace(hour=19, minute=45),
        contract_json=quote(BASE, direction).model_dump_json(),
        completed_evidence_json=canonical({"fixture": "synthetic completed bars", "planning_risk_exact": 2}),
        configuration_json=canonical({"revision": "synthetic", "source": "test"}),
        strategy_version="parlay-v1-session-v2")
    return replace(value, **changes)


def candle(minute, *, low=99.9, high=100.3, close=100.2):
    return CandleOut(symbol="SPY", timeframe="1m", timestamp=BASE+timedelta(minutes=minute),
        open=close, low=low, high=high, close=close, volume=1000)


def step(s, state, minute, bars, q=None, *, seconds=5, capacity=True):
    now = BASE+timedelta(minutes=minute, seconds=seconds)
    return advance(s, state, now=now, candles=bars, quote=q, capacity_available=capacity)


def pending(direction="call"):
    s = setup(direction)
    bar = candle(1) if direction == "call" else candle(1, low=99.7, high=100.1, close=99.8)
    q = quote(BASE+timedelta(minutes=2, seconds=5), direction)
    state = step(s, start(s), 2, [bar], q)
    assert state.phase == "PENDING_ENTRY"
    return s, state


@pytest.mark.parametrize("direction", ["call", "put"])
def test_retest_requests_then_requires_a_later_quote(direction):
    s, state = pending(direction)
    original = quote(state.requested_at, direction)
    waiting = advance(s, state, now=state.requested_at+timedelta(seconds=1),
        candles=[], quote=original, capacity_available=True)
    assert waiting.phase == "PENDING_ENTRY"
    q = quote(state.requested_at+timedelta(seconds=2), direction)
    eligible = advance(s, waiting, now=q.timestamp, candles=[], quote=q, capacity_available=True)
    assert eligible.phase == "ENTRY_ELIGIBLE"
    assert not any("FILL" in json.loads(e)["kind"] for e in eligible.events)
    assert eligible.requested_at == state.requested_at


def test_breakout_bar_cannot_retest_itself_or_use_uncompleted_bar():
    s = setup()
    value = step(s, start(s), 1, [candle(0), candle(1)], seconds=30)
    assert value.phase == "WAIT_RETEST" and value.retest_at is None


@pytest.mark.parametrize("direction", ["call", "put"])
def test_close_exactly_at_breakout_is_not_a_retest(direction):
    s = setup(direction)
    state = step(s, start(s), 2, [candle(1, close=100)],
                 quote(BASE+timedelta(minutes=2, seconds=5), direction))
    assert state.phase == "WAIT_RETEST"


def test_duplicate_identical_bars_do_not_advance_the_window_twice():
    s = setup()
    bar = candle(1, low=100.1)
    state = step(s, start(s), 2, [bar, bar])
    assert state.phase == "WAIT_RETEST"
    assert sum(json.loads(e)["kind"] == "COMPLETED_BAR" for e in state.events) == 1


@pytest.mark.parametrize("low,high,reason", [(99, 100.3, "STOP_BEFORE_ENTRY"),
    (99.9, 103, "TARGET_BEFORE_ENTRY"), (99, 103, "STOP_BEFORE_ENTRY")])
def test_touch_cancels_before_same_bar_retest(low, high, reason):
    s = setup()
    value = step(s, start(s), 2, [candle(1, low=low, high=high)])
    assert value.phase == "CANCELLED" and value.reason == reason


def test_put_touch_cancels_before_retest():
    s = setup("put")
    value = step(s, start(s), 2, [candle(1, low=99.7, high=101, close=99.8)])
    assert value.reason == "STOP_BEFORE_ENTRY"


@pytest.mark.parametrize("low,high,reason", [(99, 100.3, "STOP_BEFORE_ENTRY"),
    (99.9, 103, "TARGET_BEFORE_ENTRY")])
def test_pending_bar_invalidation_precedes_an_otherwise_valid_entry(low, high, reason):
    s, state = pending()
    q = quote(BASE+timedelta(minutes=3, seconds=5))
    value = step(s, state, 3, [candle(2, low=low, high=high)], q)
    assert value.reason == reason


def test_five_bar_expiry_and_no_sixth_retest():
    s = setup()
    bars = [candle(i, low=100.1) for i in range(1, 6)]
    state = step(s, start(s), 6, bars)
    assert state.reason == "FIVE_BAR_EXPIRY"
    assert step(s, state, 7, [candle(6)]) == state


def test_fifth_bar_retest_can_still_wait_for_later_quote():
    s = setup()
    bars = [candle(i, low=100.1) for i in range(1, 5)]+[candle(5)]
    state = step(s, start(s), 6, bars, quote(BASE+timedelta(minutes=6, seconds=5)))
    assert state.phase == "PENDING_ENTRY"
    value = step(s, state, 6, [], quote(BASE+timedelta(minutes=6, seconds=6)), seconds=6)
    assert value.phase == "ENTRY_ELIGIBLE"


@pytest.mark.parametrize("pending_entry", [False, True])
def test_missing_candle_cancels_even_when_quote_is_good(pending_entry):
    s, state = pending() if pending_entry else (setup(), start(setup()))
    value = step(s, state, 3, [], quote(BASE+timedelta(minutes=3, seconds=5)))
    assert value.reason == "MISSING_REQUIRED_CANDLE"


def test_no_backdated_request_for_an_old_retest_after_outage():
    s = setup()
    value = step(s, start(s), 3, [candle(1), candle(2)], quote(BASE+timedelta(minutes=3, seconds=5)))
    assert value.reason == "LATE_RETEST_OBSERVATION"


def test_expiry_does_not_reset_on_repeated_quotes():
    s, state = pending()
    q = quote(state.requested_at)
    waiting = step(s, state, 3, [candle(2, low=100.1)], q)
    assert waiting.phase == "PENDING_ENTRY" and waiting.requested_at == state.requested_at
    expired = step(s, waiting, 4, [candle(3, low=100.1)], q, seconds=6)
    assert expired.reason == "ENTRY_QUOTE_DEADLINE"


def test_entry_quote_at_exact_deadline_allowed_only_after_all_completed_bars():
    s, state = pending()
    q = quote(state.requested_at+timedelta(seconds=120))
    value = advance(s, state, now=q.timestamp,
        candles=[candle(2, low=100.1), candle(3, low=100.1)], quote=q, capacity_available=True)
    assert value.phase == "ENTRY_ELIGIBLE"


@pytest.mark.parametrize("changes", [
    {"received_at": None}, {"receipt_basis": "UNKNOWN"},
    {"received_at": BASE}, {"bid_timestamp": BASE}, {"ask_timestamp": BASE},
    {"received_at": BASE+timedelta(days=1)}, {"received_at": BASE.replace(tzinfo=None)},
])
def test_bad_receipt_or_quote_times_cannot_support_entry(changes):
    s, state = pending()
    q = quote(state.requested_at+timedelta(seconds=2), **changes)
    value = advance(s, state, now=q.timestamp, candles=[], quote=q, capacity_available=True)
    assert value.phase == "PENDING_ENTRY"


@pytest.mark.parametrize("changes", [
    {"option_symbol": "SPY261027C00101000", "strike": 101}, {"right": "put"},
    {"provider": "tradier"}, {"volume": 0}, {"open_interest": 0},
    {"ask": .51}, {"ask": .39, "bid": .38}, {"ask": float("nan")},
])
def test_contract_identity_and_eligibility_rechecked(changes):
    s, state = pending()
    q = quote(state.requested_at+timedelta(seconds=2), **changes)
    value = advance(s, state, now=q.timestamp, candles=[], quote=q, capacity_available=True)
    assert value.phase == "CANCELLED" and value.reason == "ENTRY_VERIFICATION_FAILED"


def test_retest_needs_verifiable_current_contract_not_future_replacement():
    s = setup()
    value = step(s, start(s), 2, [candle(1)], None)
    assert value.reason == "RETEST_VERIFICATION_FAILED"


@pytest.mark.parametrize("risk,reason", [(2, None), (1, "EXTENSION_EXCEEDED")])
def test_extension_uses_exact_frozen_planning_risk_not_stop_distance(risk, reason):
    s = setup(planning_risk=risk)
    value = step(s, start(s), 2, [candle(1, high=102.1, close=102)],
                 quote(BASE+timedelta(minutes=2, seconds=5)))
    assert value.reason == reason
    assert value.phase == ("PENDING_ENTRY" if reason is None else "CANCELLED")


@pytest.mark.parametrize("pending_entry", [False, True])
def test_capacity_failure_terminal_at_request_or_pending_entry(pending_entry):
    s, state = pending() if pending_entry else (setup(), start(setup()))
    value = step(s, state, 2, [] if pending_entry else [candle(1)],
        quote(BASE+timedelta(minutes=2, seconds=6)), seconds=6, capacity=False)
    assert value.reason == "CAPACITY_SKIP"


def test_terminal_and_repeated_processing_idempotent_after_serialization():
    s, state = pending()
    restored_setup = FrozenSetup.from_json(s.to_json())
    restored_state = TimingState.from_json(state.to_json())
    assert restored_setup == s and restored_state == state
    assert advance(s, restored_state, now=state.processed_at, candles=[], quote=None,
                   capacity_available=True) == state
    cancelled = advance(s, state, now=s.entry_cutoff, candles=[], quote=None, capacity_available=True)
    assert cancelled.reason == "SESSION_CUTOFF"
    assert advance(s, cancelled, now=s.entry_cutoff+timedelta(days=1), candles=[], quote=None,
                   capacity_available=True) == cancelled


def test_cannot_swap_frozen_plan():
    s, state = pending()
    with pytest.raises(ValueError, match="replace"):
        advance(replace(s, breakout=100.1), state, now=state.processed_at, candles=[], quote=None,
                capacity_available=True)


def test_early_close_requires_explicit_cutoffs_and_naive_timestamps_fail():
    s = setup()
    early = BASE.replace(month=11, day=27, hour=15)
    q = quote(early).model_copy(update={"expiration": early.date(), "option_symbol": "SPY261127C00100000"})
    with pytest.raises(ValueError, match="cutoffs"):
        replace(s, breakout_at=early, observed_at=early+MINUTE,
            contract_json=q.model_dump_json(), entry_cutoff=early.replace(hour=20), timed_exit=early.replace(hour=20))
    with pytest.raises(ValueError, match="timezone"):
        replace(s, observed_at=s.observed_at.replace(tzinfo=None))


MINUTE = timedelta(minutes=1)


def test_conflicting_bars_and_invalid_ohlc_fail_closed():
    s = setup()
    value = step(s, start(s), 2, [candle(1), candle(1, high=100.4)])
    assert value.reason == "CONFLICTING_CANDLE"
    value = step(s, start(s), 2, [candle(1, high=99)])
    assert value.reason == "INVALID_CANDLE"


def test_unchanged_baseline_modules_have_no_dependency_on_experiment():
    from pathlib import Path
    root = Path(__file__).parents[1]/"app"/"services"
    for name in ("parlay.py", "structured_intraday.py", "performance.py", "signal_engine.py",
                 "forward_account.py", "lotto_trials.py"):
        assert "retest_research" not in (root/name).read_text()


def test_frozen_sessions_include_outages_and_zero_trade_days_by_calendar():
    dates = evaluation_sessions(BASE)
    assert len(dates) == 60 and dates[0] == BASE.date()
    assert datetime(2026, 11, 26).date() not in dates
    assert datetime(2026, 11, 27).date() in dates
    assert evaluation_sessions(BASE.replace(hour=22))[0] == BASE.date()+timedelta(days=1)
    with pytest.raises(ValueError, match="Calendar"):
        evaluation_sessions(BASE.replace(year=2029))


def test_paired_bootstrap_repeatable_and_constant_advantage_exact():
    result = paired_block_bootstrap([0.]*60, [1.]*60)
    assert result == paired_block_bootstrap([0.]*60, [1.]*60)
    assert result["advantage_dollars"] == 60 and result["percentile_95_dollars"] == [60, 60]
    assert paired_block_bootstrap([0.]*60, [0.]*60)["percentile_95_dollars"] == [0, 0]
    correlated = [float(i % 7-3) for i in range(60)]
    assert paired_block_bootstrap(correlated, correlated)["percentile_95_dollars"] == [0, 0]


def test_unknown_valuation_is_not_a_zero_day_and_short_experiment_not_evaluated():
    assert paired_block_bootstrap([0.]*60, [None]+[0.]*59)["status"] == "INCONCLUSIVE"
    assert paired_block_bootstrap([0.]*60, [float("nan")]+[0.]*59)["status"] == "INCONCLUSIVE"
    with pytest.raises(ValueError, match="60"):
        paired_block_bootstrap([0.]*59, [0.]*59)
