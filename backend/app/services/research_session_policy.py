"""Separately versioned prospective baseline; never applied to legacy ledgers."""
from datetime import date, datetime, timedelta, timezone

from app.services.market_calendar import HOLIDAYS_BY_YEAR, NY, is_market_day, market_close

VERSION = "session-close-minus15-v1"


def session_limits(day: date) -> dict[str, datetime]:
    if day.year not in HOLIDAYS_BY_YEAR or not is_market_day(day):
        raise ValueError("Unreviewed or closed exchange date")
    close = datetime.combine(day, market_close(day), NY).astimezone(timezone.utc)
    cutoff = close-timedelta(minutes=15)
    return {"close": close, "entry_cutoff": cutoff, "timed_exit_candle": cutoff}
