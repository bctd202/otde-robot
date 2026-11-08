"""Prospective underlying benchmark and explicit candle-order uncertainty.

These are stock-price research benchmarks, not option fills. No old row adopts
this convention merely because the server is upgraded.
"""
from datetime import datetime, timedelta, timezone
import math
from app.services.market_calendar import NY
from app.services.research_session_policy import session_limits

VERSION = "post-confirmation-quote-v1"


def utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def benchmark(candidate) -> dict:
    at = utc(candidate.generated_at)
    raw = (candidate.input_evidence or {}).get("evaluation_at")
    error = None
    try:
        boundary = utc(datetime.fromisoformat(raw)) if raw else at.replace(second=0, microsecond=0)-timedelta(minutes=1)
    except (TypeError, ValueError):
        boundary = at.replace(second=0, microsecond=0)-timedelta(minutes=1)
        error = "INVALID_CONFIRMATION_EVIDENCE"
    entry = candidate.underlying_price
    stop, target = candidate.underlying_invalidation, candidate.first_underlying_target
    if not all(isinstance(p, (float, int)) and math.isfinite(p) and p > 0 for p in (entry, stop, target)):
        error = "INVALID_BENCHMARK_PRICES"
    elif not (stop < entry < target if candidate.direction == "call" else target < entry < stop):
        error = "PLAN_ALREADY_INVALID_AT_BENCHMARK"
    elif boundary.second or boundary.microsecond or not boundary+timedelta(minutes=1) <= at < boundary+timedelta(minutes=2):
        error = "QUOTE_NOT_IN_POST_CONFIRMATION_MINUTE"
    try:
        limits = session_limits(at.astimezone(NY).date())
        if at >= limits["timed_exit_candle"]+timedelta(minutes=1):
            error = "BENCHMARK_AFTER_TIMED_EXIT"
    except ValueError:
        error = "UNREVIEWED_OR_CLOSED_EXCHANGE_SESSION"
    return {"version": VERSION, "basis": "UNDERLYING_QUOTE_BENCHMARK_NOT_OPTION_FILL",
        "underlying_trigger": candidate.underlying_trigger, "entry_quote_price": entry,
        "entry_quote_at": at.isoformat(), "confirmation_candle_at": boundary.isoformat(),
        "confirmation_boundary_basis": "SAVED_INPUT_EVIDENCE" if raw else "QUOTE_CLOCK_CONVENTION",
        "first_evaluation_candle_at": at.replace(second=0, microsecond=0).isoformat(),
        "partial_entry_minute": bool(at.second or at.microsecond), "quality_error": error}


def definition(row) -> dict | None:
    value = (row.strategy_snapshot or {}).get("result_model")
    return value if value and value.get("version") == VERSION else None


def exit_completed_at(row) -> datetime | None:
    if row.exit_at is None:
        return None
    return utc(row.exit_at)+(timedelta() if definition(row) else timedelta(minutes=1))


def entry_evidence_current(row, now: datetime) -> bool:
    if not definition(row):
        return True
    boundary = utc(now).replace(second=0, microsecond=0)-timedelta(minutes=1)
    return row.last_evaluated_at is not None and utc(row.last_evaluated_at) >= boundary


def candle_range(row, candle) -> tuple[float, float, float, str | None]:
    """A completed partial-entry bar cannot establish pre/post-entry ordering.

    A close beyond just one boundary proves that side was reached after entry.
    A wick-only touch or both boundaries remains unknown; do not award a fill or
    silently skip the minute. Pre-entry highs/lows never inflate excursion.
    """
    policy = definition(row)
    high, low, close = candle.high, candle.low, candle.close
    if not policy:
        return high, low, close, None
    if (not all(math.isfinite(p) and p > 0 for p in (candle.open,high,low,close))
            or not low <= min(candle.open,close) <= max(candle.open,close) <= high):
        return high, low, close, "INVALID_POST_ENTRY_CANDLE"
    stamp = utc(candle.timestamp)
    expected = utc(row.last_evaluated_at)+timedelta(minutes=1)
    if stamp != expected:
        return high, low, close, "MISSING_POST_ENTRY_CANDLE"
    if policy["partial_entry_minute"] and stamp.isoformat() == policy["first_evaluation_candle_at"]:
        target = high >= row.target_price if row.direction == "CALL" else low <= row.target_price
        stop = low <= row.stop_price if row.direction == "CALL" else high >= row.stop_price
        target_close = close >= row.target_price if row.direction == "CALL" else close <= row.target_price
        stop_close = close <= row.stop_price if row.direction == "CALL" else close >= row.stop_price
        if (target and stop) or (target and not target_close) or (stop and not stop_close):
            return high, low, close, "ENTRY_MINUTE_ORDER_UNKNOWN"
        return close, close, close, None
    return high, low, close, None
