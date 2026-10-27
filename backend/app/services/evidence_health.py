"""Read-only collection diagnostics. Never change selection or ledger records."""
from datetime import date, datetime, timedelta, timezone
import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ScannerRuntime, SignalScan
from app.services.market_calendar import NY, REGULAR_OPEN, is_market_day, market_close, market_session


def utc(stamp: datetime) -> datetime:
    return stamp.astimezone(timezone.utc) if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def collection_evidence(db: Session, now: datetime, runtime: ScannerRuntime | None) -> dict:
    now = utc(now)
    local = now.astimezone(NY)
    day = local.date()
    if not is_market_day(day) or local.time() < REGULAR_OPEN:
        day -= timedelta(days=1)
    days: list[date] = []
    while len(days) < 5:
        if is_market_day(day):
            days.append(day)
        day -= timedelta(days=1)
    start = datetime.combine(days[-1], REGULAR_OPEN, NY).astimezone(timezone.utc)
    stamps = db.execute(select(SignalScan.evaluation_candle_at, SignalScan.scanned_at).where(
        SignalScan.scanned_at >= start, SignalScan.scanned_at <= now)).all()
    sessions: list[dict] = []
    for day in days:
        opening = datetime.combine(day, REGULAR_OPEN, NY).astimezone(timezone.utc)
        close = datetime.combine(day, market_close(day), NY).astimezone(timezone.utc)
        boundary = min(close, now.replace(second=0, microsecond=0))
        expected = max(0, int((boundary-opening).total_seconds() // 60))
        minutes = {utc(candle).replace(second=0, microsecond=0) for candle, scanned in stamps
                   if opening <= utc(candle) < boundary
                   and utc(candle) <= utc(scanned) <= close + timedelta(minutes=5)}
        sessions.append({"date": day.isoformat(), "expected_minutes": expected,
                         "observed_minutes": len(minutes), "missing_minutes": max(0, expected-len(minutes)),
                         "coverage_percent": round(100*len(minutes)/expected, 1) if expected else None,
                         "complete_session": now >= close})
    age = None
    # Read only the latest bounded window, not every saved candidate payload.
    recent = db.execute(select(SignalScan.scanned_at, SignalScan.provider_status).where(
        SignalScan.scanned_at >= start, SignalScan.scanned_at <= now)
        .order_by(SignalScan.scanned_at.desc()).limit(120)).all()
    measured = [(at, payload['scan_timing_v1']) for at, payload in recent
                if isinstance(payload, dict) and isinstance(payload.get('scan_timing_v1'), dict)
                and isinstance(payload['scan_timing_v1'].get('total_ms'), (int, float))
                and math.isfinite(payload['scan_timing_v1']['total_ms'])
                and payload['scan_timing_v1']['total_ms'] >= 0]
    durations = sorted(timing['total_ms']/1000 for _, timing in measured)
    timing_summary = {'measured_scans': len(durations), 'window_scans': len(recent),
        'over_minute_scans': sum(duration >= 60 for duration in durations),
        'p95_seconds': round(durations[math.ceil(.95*len(durations))-1], 2) if durations else None,
        'latest_at': utc(measured[0][0]).isoformat() if measured else None,
        'latest_phases_ms': measured[0][1].get('phases_ms', {}) if measured else {},
        'basis': 'Last 120 saved scans within five sessions. New instrumentation only; no historical timing inferred. Work time excludes the final database commit. A run over 60 seconds can overlap the next scheduled scan; it is not proof of the cause of every gap.'}
    if runtime and runtime.last_evaluation_candle_at:
        age = round((now-utc(runtime.last_evaluation_candle_at)).total_seconds())
    if runtime and runtime.operator_hold:
        status = "HELD"
    elif market_session(now) != "regular":
        status = "CLOSED"
    elif (local-datetime.combine(local.date(), REGULAR_OPEN, NY)).total_seconds() < 180:
        status = "WARMING_UP"
    else:
        status = "CURRENT" if age is not None and 0 <= age <= 180 else "STALE"
    return {"status": status, "evaluation_age_seconds": age, "sessions": sessions,
            "scan_timing": timing_summary,
            "has_coverage_gaps": any(row["missing_minutes"] > 0 for row in sessions),
            "basis": "Unique saved regular-session evaluation minutes; not proof of valid quotes or every ticker's candles.",
            "historical_records_changed": False}
