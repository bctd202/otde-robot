"""Contract lifecycle facts, not inferred sales, exercise or settlement values."""
from datetime import datetime

from app.services.market_calendar import NY, market_close
from app.services.option_research import utc

VERSION = "session-end-state-v1"
ENDED_UNRESOLVED = "ENDED_UNRESOLVED"


def final_session_end(mark) -> datetime:
    # This is the paper account's regular-session boundary, not a claim that
    # every ETF option stops trading or completes exercise processing at 16:00.
    return datetime.combine(mark.expiration, market_close(mark.expiration), NY)


def fields(mark, status: str, now: datetime) -> dict:
    expired = utc(now).astimezone(NY).date() > mark.expiration
    ended = status == ENDED_UNRESOLVED
    label = ("Expired · exit price missing" if expired else "Session ended · exit price missing") if ended else None
    return {"expiration": mark.expiration.isoformat(), "trading_date": mark.trading_date.isoformat(),
            "entry_dte": (mark.expiration-mark.trading_date).days,
            "lifecycle_label": label, "capacity_released": ended}
