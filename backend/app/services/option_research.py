"""Fixed forward experiments using cached quotes; no orders or strategy mutations."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import math
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import AutomatedOptionMark, AutomatedOptionObservation, SignalPerformance
from app.services.contracts import validate_exit_quote

NY = ZoneInfo("America/New_York")
RESEARCH_VERSION = "option-path-v1"
MAX_OBSERVATIONS_PER_SCAN = 40
MAX_QUOTE_AGE_SECONDS = 60
MAX_HORIZON_LAG_SECONDS = 90
HOLD_MINUTES = (15, 30, 60)


def utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


@lru_cache(maxsize=1)
def research_definition() -> dict:
    digest = hashlib.sha256()
    for name in ("parlay.py", "structured_intraday.py", "performance.py", "option_research.py"):
        digest.update((Path(__file__).parent / name).read_bytes())
    settings = get_settings()
    # Explicit safe allowlist: never serialize settings wholesale (credentials live there).
    configuration = {"provider": settings.market_data_provider,
        "configured_universe": settings.parlay_symbol_list,
        "flex_limit": settings.parlay_flex_limit,
        "option_shadow_enabled": settings.automated_option_shadow_enabled,
        "exit_quote_lag_seconds": settings.automated_option_max_quote_lag_seconds,
        "scan_second": settings.parlay_scan_second}
    return {"version": RESEARCH_VERSION, "code_fingerprint": digest.hexdigest()[:16],
            "configuration": configuration,
            "maximum_hold_minutes": list(HOLD_MINUTES), "max_quote_age_seconds": MAX_QUOTE_AGE_SECONDS,
            "max_horizon_lag_seconds": MAX_HORIZON_LAG_SECONDS, "collection": "CACHE_ONLY",
            "core_tickers": ["IWM", "QQQ", "SPY"]}


def record_option_observations(db: Session, provider, *, now: datetime | None = None) -> None:
    """Once per minute per accepted contract, after exit processing, with zero requests.

    A gap is evidence, not a fabricated quote. Existing records are never backfilled.
    """
    now = utc(now or datetime.now(timezone.utc))
    local = now.astimezone(NY)
    if local.weekday() >= 5 or not (9*60+30 <= local.hour*60+local.minute < 16*60):
        return
    minute = now.replace(second=0, microsecond=0)
    existing = set(db.scalars(select(AutomatedOptionObservation.signal_id).where(
        AutomatedOptionObservation.minute_at == minute)).all())
    entries = db.execute(select(AutomatedOptionMark, SignalPerformance).join(
        SignalPerformance, SignalPerformance.signal_id == AutomatedOptionMark.signal_id
    ).where(AutomatedOptionMark.mark_type == "ENTRY", SignalPerformance.exit_reason == "OPEN",
            AutomatedOptionMark.trading_date == local.date()).order_by(
                AutomatedOptionMark.event_at, AutomatedOptionMark.id)).all()
    status = provider.status()
    count = 0
    cache: dict[tuple, list] = {}
    for entry, row in entries:
        definition = (row.strategy_snapshot or {}).get("option_research", {})
        if (definition.get("version") != RESEARCH_VERSION or row.signal_id in existing
                or utc(entry.observed_at) > now or count >= MAX_OBSERVATIONS_PER_SCAN):
            continue
        count += 1
        reason = "No fresh cached quote for accepted contract"
        selected = None
        if status.status == "healthy" and status.mode == "live" and hasattr(provider, "cached_option_chain"):
            key = (entry.ticker, entry.expiration)
            if key not in cache:
                try:
                    cache[key] = provider.cached_option_chain(*key) or []
                except (KeyError, ValueError, RuntimeError):
                    cache[key] = []
            candidate = next((c for c in cache[key]
                              if c.option_symbol.strip().upper() == entry.normalized_option_symbol), None)
            if candidate is not None:
                decision = validate_exit_quote(candidate, entry.ticker, entry.normalized_option_symbol,
                    now-timedelta(seconds=MAX_QUOTE_AGE_SECONDS), MAX_QUOTE_AGE_SECONDS)
                reason = decision.reason
                if (decision.actionable and math.isfinite(candidate.bid) and math.isfinite(candidate.ask)
                        and candidate.bid_timestamp is not None
                        and utc(candidate.bid_timestamp) >= utc(entry.observed_at)):
                    selected = candidate
                    reason = "Verified exact live contract within observation freshness window"
                elif decision.actionable:
                    reason = "Non-finite price or quote predates the accepted entry"
        db.add(AutomatedOptionObservation(signal_id=row.signal_id, minute_at=minute, observed_at=now,
            option_symbol=entry.normalized_option_symbol, status="QUOTED" if selected else "GAP",
            reason=reason[:255], bid=selected.bid if selected else None, ask=selected.ask if selected else None,
            bid_timestamp=utc(selected.bid_timestamp) if selected and selected.bid_timestamp else None,
            ask_timestamp=utc(selected.ask_timestamp) if selected and selected.ask_timestamp else None,
            provider=selected.provider if selected else status.provider,
            cohort=f"{RESEARCH_VERSION}:{definition.get('code_fingerprint', 'unknown')}"))
    db.flush()


def option_path_research(db: Session, rows: list[SignalPerformance], *, fixed_cost: float = 1) -> dict:
    ids = {r.signal_id for r in rows}
    points = list(db.scalars(select(AutomatedOptionObservation).where(
        AutomatedOptionObservation.signal_id.in_(ids)).order_by(
            AutomatedOptionObservation.observed_at, AutomatedOptionObservation.id)).all()) if ids else []
    pairs: dict[str, dict] = defaultdict(dict)
    for m in db.scalars(select(AutomatedOptionMark).where(AutomatedOptionMark.signal_id.in_(ids))):
        pairs[m.signal_id][m.mark_type] = m
    grouped: dict[str, list] = defaultdict(list)
    for p in points:
        grouped[p.signal_id].append(p)
    scenarios = []
    for minutes in HOLD_MINUTES:
        n = incomplete = 0
        baseline_pnl = alternative_pnl = 0.0
        for row in rows:
            definition = (row.strategy_snapshot or {}).get("option_research", {})
            if definition != research_definition():
                continue  # Never blend revisions into the current forward experiment.
            entry, exit_mark = pairs[row.signal_id].get("ENTRY"), pairs[row.signal_id].get("EXIT")
            if entry is None or row.exit_reason == "OPEN":
                continue
            if (exit_mark is None or exit_mark.mark_status != "QUOTED" or
                    entry.selected_price is None or exit_mark.selected_price is None):
                incomplete += 1
                continue
            deadline = utc(entry.observed_at)+timedelta(minutes=minutes)
            baseline_time = max(utc(exit_mark.observed_at), utc(exit_mark.event_at))
            if baseline_time <= deadline:
                bid = exit_mark.selected_price
            else:
                point = next((p for p in grouped[row.signal_id] if p.status == "QUOTED"
                    and p.bid is not None and p.bid_timestamp is not None
                    and deadline <= utc(p.bid_timestamp) <= utc(p.observed_at)
                    and deadline <= utc(p.observed_at) <= min(
                        baseline_time, deadline+timedelta(seconds=MAX_HORIZON_LAG_SECONDS))), None)
                if point is None:
                    incomplete += 1
                    continue
                bid = point.bid
            n += 1
            baseline_pnl += (exit_mark.selected_price-entry.selected_price)*entry.contract_multiplier-fixed_cost
            alternative_pnl += (bid-entry.selected_price)*entry.contract_multiplier-fixed_cost
        scenarios.append({"maximum_hold_minutes": minutes, "matched_plays": n, "incomplete_plays": incomplete,
            "baseline_net_dollars": round(baseline_pnl, 2), "alternative_net_dollars": round(alternative_pnl, 2),
            "difference_dollars": round(alternative_pnl-baseline_pnl, 2)})
    return {"definition": research_definition(), "observations": len(points),
            "quoted_observations": sum(p.status == "QUOTED" for p in points),
            "gap_observations": sum(p.status != "QUOTED" for p in points),
            "observed_plays": len(grouped), "fixed_cost_per_contract": fixed_cost,
            "scenarios": scenarios, "additional_requests": 0,
            "note": "Fixed maximum-hold experiments keep an earlier baseline exit. "
                    "Only matched plays with saved quotes are compared. Gaps are excluded, never priced at zero. "
                    "Results use the current code cohort and are exploratory; no orders or exit rules are changed."}
