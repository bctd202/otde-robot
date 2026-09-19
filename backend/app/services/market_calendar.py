from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
HOLIDAYS_2026 = {date(2026,1,1), date(2026,1,19), date(2026,2,16), date(2026,4,3), date(2026,5,25), date(2026,6,19), date(2026,7,3), date(2026,9,7), date(2026,11,26), date(2026,12,25)}
EARLY_CLOSES_2026 = {date(2026,11,27), date(2026,12,24)}
HOLIDAYS_BY_YEAR = {
    2026: HOLIDAYS_2026,
    2027: {date(2027,1,1), date(2027,1,18), date(2027,2,15), date(2027,3,26),
           date(2027,5,31), date(2027,6,18), date(2027,7,5), date(2027,9,6),
           date(2027,11,25), date(2027,12,24)},
    2028: {date(2028,1,17), date(2028,2,21), date(2028,4,14), date(2028,5,29),
           date(2028,6,19), date(2028,7,4), date(2028,9,4), date(2028,11,23),
           date(2028,12,25)},
}
EARLY_CLOSES_BY_YEAR = {
    2026: EARLY_CLOSES_2026,
    2027: {date(2027,11,26)},
    2028: {date(2028,7,3), date(2028,11,24)},
}

REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)

def is_market_day(d: date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS_BY_YEAR.get(d.year, set())


def market_close(d: date) -> time:
    return EARLY_CLOSE if d in EARLY_CLOSES_BY_YEAR.get(d.year, set()) else REGULAR_CLOSE

def market_session(now: datetime) -> str:
    n = now.astimezone(NY)
    if not is_market_day(n.date()): return "closed_holiday_or_weekend"
    close = market_close(n.date())
    if time(4,0) <= n.time() < time(9,30): return "premarket"
    if time(9,30) <= n.time() < close: return "regular"
    return "closed"


def next_market_open(now: datetime) -> datetime:
    """Return the next regular-session opening bell strictly after closed time."""
    local = now.astimezone(NY)
    if is_market_day(local.date()) and local.time() < REGULAR_OPEN:
        return datetime.combine(local.date(), REGULAR_OPEN, NY)
    day = local.date() + timedelta(days=1)
    while not is_market_day(day):
        day += timedelta(days=1)
    return datetime.combine(day, REGULAR_OPEN, NY)


def next_scanner_run(now: datetime, second: int = 5) -> datetime:
    """Return the next regular scan or the single session-close housekeeping run.

    The returned schedule is silent overnight, on weekends, and on configured
    exchange holidays. The close run intentionally remains so active lifecycle
    and lottery records receive their normal end-of-session housekeeping.
    """
    local = now.astimezone(NY)
    scan_second = max(0, min(second, 59))
    candidate = local.replace(second=scan_second, microsecond=0)
    if candidate <= local:
        candidate += timedelta(minutes=1)
    while True:
        if is_market_day(candidate.date()):
            open_run = datetime.combine(candidate.date(), REGULAR_OPEN, NY).replace(second=scan_second)
            close_run = datetime.combine(candidate.date(), market_close(candidate.date()), NY).replace(
                second=scan_second
            )
            if candidate < open_run:
                return open_run
            if candidate <= close_run:
                return candidate
        next_open = next_market_open(candidate)
        candidate = next_open.replace(second=scan_second)
