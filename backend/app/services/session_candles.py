"""Session-bound inputs for live decisions, never a historical-record rewrite."""
from datetime import datetime, timedelta, timezone

from app.schemas.market import CandleOut
from app.services.indicators import opening_range, vwap
from app.services.market_calendar import NY, REGULAR_OPEN, is_market_day, market_close

INPUT_VERSION = "current-session-v2"


def utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def session_candles(rows: list[CandleOut], completed_at: datetime) -> list[CandleOut]:
    boundary = utc(completed_at)
    # At 09:30 the evaluation boundary is 09:29, still belonging to today's decision.
    day = (boundary + timedelta(minutes=1)).astimezone(NY).date()
    if not is_market_day(day):
        return []
    start = datetime.combine(day, REGULAR_OPEN, NY)
    end = datetime.combine(day, market_close(day), NY)
    selected = {utc(row.timestamp): row for row in rows
                if start <= utc(row.timestamp) < end and utc(row.timestamp) <= boundary}
    return [selected[stamp] for stamp in sorted(selected)]


def session_evidence(rows: list[CandleOut], completed_at: datetime) -> dict:
    return {"input_version": INPUT_VERSION,
            "session_date": (utc(completed_at)+timedelta(minutes=1)).astimezone(NY).date().isoformat(),
            "evaluation_at": utc(completed_at).isoformat(), "candle_count": len(rows),
            "first_candle_at": utc(rows[0].timestamp).isoformat() if rows else None,
            "last_candle_at": utc(rows[-1].timestamp).isoformat() if rows else None,
            "opening_range": opening_range(rows, 5) if len(rows) >= 5 else None,
            "vwap": vwap(rows) if rows else None}
