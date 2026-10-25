"""Reporting-only diagnostics, separate from fingerprinted trading/mark logic."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AutomatedOptionMark, SignalPerformance
from app.services.evidence_health import utc


def shadow_evidence_audit(db: Session, rows: list[SignalPerformance], shadows: dict[str, dict]) -> dict:
    quoted_rows = [row for row in rows if shadows.get(row.signal_id, {}).get("status") == "CLOSED"]
    ids = [row.signal_id for row in quoted_rows]
    marks = db.scalars(select(AutomatedOptionMark).where(AutomatedOptionMark.signal_id.in_(ids))).all() if ids else []
    pairs = {(mark.signal_id, mark.mark_type): mark for mark in marks}
    daily: dict[str, float] = {}
    flagged = []
    for row in quoted_rows:
        shadow = shadows[row.signal_id]
        pnl = shadow["pnl_dollars"]
        day = row.trading_date.isoformat()
        daily[day] = daily.get(day, 0) + pnl
        entry, exit_mark = pairs[(row.signal_id, "ENTRY")], pairs[(row.signal_id, "EXIT")]
        flags = []
        for label, mark in (("ENTRY", entry), ("EXIT", exit_mark)):
            if mark.quote_timestamp is None:
                flags.append(f"{label}_QUOTE_TIME_MISSING")
            elif utc(mark.quote_timestamp) > utc(mark.observed_at):
                flags.append(f"{label}_QUOTE_AFTER_RECORDED_OBSERVATION")
        if exit_mark.quote_lag_seconds is not None and exit_mark.quote_lag_seconds > 60:
            flags.append("EXIT_QUOTE_OVER_60_SECONDS_AFTER_EVENT")
        if shadow["return_percent"] is not None and shadow["return_percent"] >= 400:
            flags.append("EXIT_VALUE_AT_LEAST_5X_ENTRY")
        if flags:
            flagged.append({"signal_id": row.signal_id, "ticker": row.ticker, "date": day,
                            "pnl_dollars": pnl, "flags": flags,
                            "entry_quote_at": utc(entry.quote_timestamp) if entry.quote_timestamp else None,
                            "entry_observed_at": utc(entry.observed_at),
                            "exit_quote_at": utc(exit_mark.quote_timestamp) if exit_mark.quote_timestamp else None,
                            "exit_observed_at": utc(exit_mark.observed_at),
                            "quote_lag_seconds": exit_mark.quote_lag_seconds})
    best = max(daily, key=lambda day: daily[day]) if daily else None
    return {"quoted_trades": len(quoted_rows), "flagged_trades": len(flagged),
            "best_entry_day": best, "best_day_pnl_dollars": round(daily[best], 2) if best else None,
            "without_best_day_pnl_dollars": round(sum(daily.values())-daily[best], 2) if best else None,
            "daily": [{"date": day, "pnl_dollars": round(value, 2)} for day, value in sorted(daily.items())],
            "flagged_examples": sorted(flagged, key=lambda row: abs(row["pnl_dollars"]), reverse=True)[:10],
            "basis": "Gross quoted option P/L grouped by entry trading date, before fees. Diagnostic flags do not invalidate or exclude trades. Observation time is a provider-status timestamp, not proven receipt time. The 60-second lag and 5x thresholds are review flags, not trading rules.",
            "historical_records_changed": False}
