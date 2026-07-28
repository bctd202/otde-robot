from datetime import date, datetime, time
from zoneinfo import ZoneInfo
NY = ZoneInfo("America/New_York")
HOLIDAYS_2026 = {date(2026,1,1), date(2026,1,19), date(2026,2,16), date(2026,4,3), date(2026,5,25), date(2026,6,19), date(2026,7,3), date(2026,9,7), date(2026,11,26), date(2026,12,25)}
EARLY_CLOSES_2026 = {date(2026,11,27), date(2026,12,24)}

def is_market_day(d: date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS_2026

def market_session(now: datetime) -> str:
    n = now.astimezone(NY)
    if not is_market_day(n.date()): return "closed_holiday_or_weekend"
    close = time(13,0) if n.date() in EARLY_CLOSES_2026 else time(16,0)
    if time(4,0) <= n.time() < time(9,30): return "premarket"
    if time(9,30) <= n.time() < close: return "regular"
    return "closed"
