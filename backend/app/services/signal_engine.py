import logging
from threading import Lock
from datetime import date, datetime, timedelta, timezone
from typing import Literal, cast
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (DailyWatchSymbol, ParlayPaperPosition, ScannerRuntime,
                           SignalAlert, SignalLifecycle, SignalPerformance,
                           SignalScan)
from app.db.session import SessionLocal
from app.market_data.factory import get_provider
from app.schemas.market import ParlayCandidateOut
from app.services.market_calendar import market_session
from app.services.lottery_tracker import close_lottery_trackers, track_lottery_scan
from app.services.paper_positions import refresh_position
from app.services.parlay import latest_completed_candle_at, rank_parlays
from app.services.performance import track_candidates
from app.services.structured_intraday import rank_structured_intraday

logger = logging.getLogger(__name__)
NY = ZoneInfo("America/New_York")
ENGINE_KEY = "parlay"
ACTIVE_STATES = ("WATCH", "BUY")
SCAN_LOCK = Lock()
_BACKGROUND_PROVIDER = None


def _strategy_label(mode: str) -> str:
    return "Structured Intraday" if mode == "STRUCTURED_INTRADAY" else "1-Min / 0DTE"


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _runtime(db: Session) -> ScannerRuntime:
    row = db.get(ScannerRuntime, ENGINE_KEY)
    if row is None:
        row = ScannerRuntime(key=ENGINE_KEY, status="starting", heartbeat_at=datetime.now(timezone.utc))
        db.add(row)
        db.flush()
    return row


def _alert(db: Session, *, lifecycle: SignalLifecycle | None, symbol: str,
           event_type: str, message: str, payload: dict | None = None,
           dedupe_key: str | None = None) -> None:
    key = dedupe_key or f"{lifecycle.id if lifecycle else symbol}:{event_type}"
    if db.scalar(select(SignalAlert.id).where(SignalAlert.dedupe_key == key)) is not None:
        return
    details = dict(payload or {})
    if lifecycle is not None:
        details.setdefault("strategy_mode", lifecycle.strategy_mode)
        details.setdefault("strategy_version", lifecycle.strategy_version)
    db.add(SignalAlert(dedupe_key=key, lifecycle_id=lifecycle.id if lifecycle else None,
        symbol=symbol, event_type=event_type, message=message,
        created_at=datetime.now(timezone.utc), payload=details, acknowledged=False))


def _active_lifecycle(db: Session, symbol: str, trading_day: date,
                      strategy_mode: str) -> SignalLifecycle | None:
    return db.scalar(select(SignalLifecycle).where(
        SignalLifecycle.symbol == symbol,
        SignalLifecycle.trading_date == trading_day,
        SignalLifecycle.strategy_mode == strategy_mode,
        SignalLifecycle.status.in_(ACTIVE_STATES),
    ).order_by(SignalLifecycle.updated_at.desc()))


def _terminal_state(row: SignalLifecycle, candidate: ParlayCandidateOut) -> tuple[str, str]:
    snapshot = row.candidate_snapshot or {}
    invalidation = snapshot.get("underlying_invalidation")
    price = candidate.underlying_price
    if invalidation is not None and price is not None:
        breached = price < invalidation if row.direction == "call" else price > invalidation
        if breached:
            return "INVALIDATED", f"{row.symbol} breached its underlying invalidation"
    return "EXPIRED", f"{row.symbol} no longer qualifies on the latest completed candle"


def _end_lifecycle(db: Session, row: SignalLifecycle, status: str, reason: str,
                   ended_at: datetime, candidate: ParlayCandidateOut) -> None:
    row.status = status
    row.reason = reason
    row.ended_at = ended_at
    row.valid_until = None
    row.last_verified_at = ended_at
    row.evaluation_candle_at = ended_at - timedelta(minutes=1)
    row.candidate_snapshot = candidate.model_dump(mode="json")
    row.updated_at = datetime.now(timezone.utc)
    _alert(db, lifecycle=row, symbol=row.symbol, event_type=status, message=reason,
           payload={"direction": row.direction, "status": status})


def _new_lifecycle(db: Session, candidate: ParlayCandidateOut, trading_day: date,
                   verified_at: datetime, valid_until: datetime,
                   evaluation_at: datetime) -> SignalLifecycle:
    state = candidate.signal_status
    reason = candidate.primary_action
    row = SignalLifecycle(id=str(uuid4()), symbol=candidate.symbol,
        direction=candidate.direction, strategy_mode=candidate.strategy_mode,
        strategy_version=candidate.strategy_version,
        trading_date=trading_day, status=state,
        first_seen_at=verified_at, triggered_at=verified_at if state == "BUY" else None,
        last_verified_at=verified_at, valid_until=valid_until if state in ACTIVE_STATES else None,
        ended_at=verified_at if state == "MISSED" else None,
        evaluation_candle_at=evaluation_at, reason=reason,
        candidate_snapshot=candidate.model_dump(mode="json"),
        updated_at=datetime.now(timezone.utc))
    db.add(row)
    label = _strategy_label(candidate.strategy_mode)
    event = "NEW_WATCH" if state == "WATCH" else state
    message = (f"{candidate.symbol} {label} entered the waiting room" if state == "WATCH" else
               f"{candidate.symbol} is a verified {label} BUY" if state == "BUY" else
               f"{candidate.symbol} {label} setup was missed; do not chase")
    _alert(db, lifecycle=row, symbol=candidate.symbol, event_type=event, message=message,
           payload={"direction": candidate.direction, "action": candidate.primary_action,
                    "strategy_mode": candidate.strategy_mode,
                    "strategy_version": candidate.strategy_version})
    return row


def apply_lifecycle(db: Session, candidates: list[ParlayCandidateOut],
                    evaluation_at: datetime) -> None:
    verified_at = evaluation_at + timedelta(minutes=1)
    valid_until = evaluation_at + timedelta(minutes=2)
    trading_day = verified_at.astimezone(NY).date()
    for candidate in candidates:
        active = _active_lifecycle(db, candidate.symbol, trading_day, candidate.strategy_mode)
        current = candidate.signal_status
        if active is not None and (candidate.direction not in {active.direction, "none"}):
            state, reason = _terminal_state(active, candidate)
            _end_lifecycle(db, active, state, reason, verified_at, candidate)
            active = None

        row: SignalLifecycle | None = active
        if current in ACTIVE_STATES and candidate.direction in {"call", "put"}:
            if active is None:
                row = _new_lifecycle(db, candidate, trading_day, verified_at, valid_until, evaluation_at)
            elif active.status == "WATCH" and current == "BUY":
                active.status = "BUY"
                active.triggered_at = verified_at
                active.reason = candidate.primary_action
                _alert(db, lifecycle=active, symbol=candidate.symbol, event_type="BUY",
                       message=f"{candidate.symbol} {_strategy_label(candidate.strategy_mode)} moved from WATCH to verified BUY",
                       payload={"direction": candidate.direction, "action": candidate.primary_action,
                                "strategy_mode": candidate.strategy_mode})
            elif active.status == "BUY" and current == "WATCH":
                _end_lifecycle(db, active, "EXPIRED",
                    f"{candidate.symbol} BUY expired because the trigger no longer qualifies",
                    verified_at, candidate)
                row = _new_lifecycle(db, candidate, trading_day, verified_at, valid_until, evaluation_at)
            if row is not None:
                row.last_verified_at = verified_at
                row.valid_until = valid_until
                row.evaluation_candle_at = evaluation_at
                row.reason = candidate.primary_action
                row.candidate_snapshot = candidate.model_dump(mode="json")
                row.updated_at = datetime.now(timezone.utc)
                if (current == "BUY" and candidate.contract is not None and candidate.entry_high and
                        candidate.contract.ask >= candidate.entry_high * .95):
                    _alert(db, lifecycle=row, symbol=candidate.symbol, event_type="ENTRY_WINDOW_CLOSING",
                           message=f"{candidate.symbol} is near the top of its allowed entry range",
                           payload={"ask": candidate.contract.ask, "entry_high": candidate.entry_high})
        elif current == "MISSED" and candidate.direction in {"call", "put"}:
            if active is not None:
                _end_lifecycle(db, active, "MISSED",
                    f"{candidate.symbol} moved beyond the no-chase window", verified_at, candidate)
                row = active
            else:
                row = _new_lifecycle(db, candidate, trading_day, verified_at, valid_until, evaluation_at)
        elif active is not None:
            state, reason = _terminal_state(active, candidate)
            _end_lifecycle(db, active, state, reason, verified_at, candidate)
            row = active

        if row is not None:
            candidate.lifecycle_id = row.id
            candidate.lifecycle_status = cast(Literal["WATCH", "BUY", "ENTERED", "EXPIRED", "MISSED", "INVALIDATED"], row.status)
            candidate.first_seen_at = row.first_seen_at
            candidate.triggered_at = row.triggered_at
            candidate.last_verified_at = row.last_verified_at
            candidate.valid_until = row.valid_until
            candidate.validity_reason = row.reason
    db.flush()


def _position_alerts(db: Session, provider) -> None:
    positions = list(db.scalars(select(ParlayPaperPosition).where(
        ParlayPaperPosition.lifecycle_status == "ACTIVE")).all())
    for position in positions:
        result = refresh_position(db, position, provider)
        if result.decision_status == "TAKE_PROFIT":
            _alert(db, lifecycle=None, symbol=position.symbol, event_type="TARGET_HIT",
                   message=f"{position.symbol} paper position reached its first target",
                   payload={"position_id": position.id, "strategy_mode": position.strategy_mode},
                   dedupe_key=f"position:{position.id}:target")
        elif result.decision_status == "EXIT":
            _alert(db, lifecycle=None, symbol=position.symbol, event_type="STOP_HIT",
                   message=f"{position.symbol} paper position reached an exit condition",
                   payload={"position_id": position.id, "action": result.next_action,
                            "strategy_mode": position.strategy_mode},
                   dedupe_key=f"position:{position.id}:exit")


def _performance_alerts(db: Session) -> None:
    completed = list(db.scalars(select(SignalPerformance).where(
        SignalPerformance.source == "LIVE",
        SignalPerformance.trading_date == datetime.now(NY).date(),
        SignalPerformance.exit_reason.in_(("TARGET", "STOP")),
    )).all())
    for row in completed:
        event = "TARGET_HIT" if row.exit_reason == "TARGET" else "STOP_HIT"
        _alert(db, lifecycle=None, symbol=row.ticker, event_type=event,
               message=f"{row.ticker} research signal reached {row.exit_reason.lower()}",
               payload={"signal_id": row.signal_id, "result_r": row.result_r,
                        "strategy_mode": row.strategy_mode},
               dedupe_key=f"performance:{row.signal_id}:{row.exit_reason}")


def _run_signal_scan(db: Session, provider, universe: list[str], *, force: bool = False,
                     evaluation_at: datetime | None = None) -> SignalScan | None:
    runtime = _runtime(db)
    status = provider.status()
    evaluation_at = evaluation_at or latest_completed_candle_at(status.latest_timestamp)
    if (not force and runtime.last_evaluation_candle_at is not None and
            _utc(runtime.last_evaluation_candle_at) >= evaluation_at):
        runtime.heartbeat_at = datetime.now(timezone.utc)
        db.commit()
        return latest_scan(db)

    now = datetime.now(timezone.utc)
    runtime.status = "scanning"
    runtime.last_scan_started_at = now
    runtime.heartbeat_at = now
    runtime.last_error = None
    db.commit()
    try:
        one_minute = rank_parlays(provider, universe, completed_at=evaluation_at)
        structured = rank_structured_intraday(provider, universe, completed_at=evaluation_at)
        candidates = one_minute + structured
        apply_lifecycle(db, candidates, evaluation_at)
        track_candidates(db, candidates, provider)
        track_lottery_scan(db, provider, get_settings().symbol_list, evaluation_at)
        _position_alerts(db, provider)
        _performance_alerts(db)
        if hasattr(provider, "budget_status"):
            budget = provider.budget_status()
            remaining = budget.get("remaining")
            if remaining is not None and remaining <= 20:
                minute = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
                _alert(db, lifecycle=None, symbol="SYSTEM", event_type="API_BUDGET_LOW",
                       message=f"Tradier request capacity is low: {remaining} safe requests remain",
                       payload=budget, dedupe_key=f"api-budget:{minute}")
        final_status = provider.status()
        completed = datetime.now(timezone.utc)
        scan = SignalScan(trading_date=(evaluation_at + timedelta(minutes=1)).astimezone(NY).date(),
            scanned_at=completed, evaluation_candle_at=evaluation_at,
            provider_status=final_status.model_dump(mode="json"), universe=universe,
            candidates=[candidate.model_dump(mode="json") for candidate in candidates])
        db.add(scan)
        runtime.status = "healthy" if final_status.status == "healthy" else "degraded"
        runtime.last_scan_completed_at = completed
        runtime.last_evaluation_candle_at = evaluation_at
        runtime.next_evaluation_at = evaluation_at + timedelta(minutes=2)
        runtime.heartbeat_at = completed
        configuration_only = (
            final_status.provider == "tradier" and final_status.mode == "unknown"
            and final_status.message.startswith("Tradier data mode is unknown.")
        )
        runtime.last_error = (
            None if final_status.status == "healthy" or configuration_only
            else final_status.message[:500]
        )
        db.commit()
        db.refresh(scan)
        return scan
    except Exception as exc:
        db.rollback()
        runtime = _runtime(db)
        runtime.status = "error"
        runtime.last_error = f"{type(exc).__name__}: {exc}"[:500]
        runtime.heartbeat_at = datetime.now(timezone.utc)
        db.commit()
        raise


def run_signal_scan(db: Session, provider, universe: list[str], *, force: bool = False,
                    evaluation_at: datetime | None = None) -> SignalScan | None:
    with SCAN_LOCK:
        return _run_signal_scan(db, provider, universe, force=force, evaluation_at=evaluation_at)


def latest_scan(db: Session) -> SignalScan | None:
    return db.scalar(select(SignalScan).order_by(SignalScan.scanned_at.desc(), SignalScan.id.desc()))


def cached_candidates(scan: SignalScan, db: Session | None = None) -> list[ParlayCandidateOut]:
    candidates = [ParlayCandidateOut.model_validate(candidate) for candidate in scan.candidates]
    if db is None:
        return candidates
    for candidate in candidates:
        row = db.get(SignalLifecycle, candidate.lifecycle_id) if candidate.lifecycle_id else None
        if row is None:
            continue
        candidate.lifecycle_status = cast(Literal["WATCH", "BUY", "ENTERED", "EXPIRED", "MISSED", "INVALIDATED"], row.status)
        candidate.first_seen_at = row.first_seen_at
        candidate.triggered_at = row.triggered_at
        candidate.last_verified_at = row.last_verified_at
        candidate.valid_until = row.valid_until
        candidate.validity_reason = row.reason
    return candidates


def mark_lifecycle_entered(db: Session, position: ParlayPaperPosition) -> None:
    trading_day = _utc(position.opened_at).astimezone(NY).date()
    row = db.scalar(select(SignalLifecycle).where(
        SignalLifecycle.symbol == position.symbol,
        SignalLifecycle.direction == position.direction,
        SignalLifecycle.strategy_mode == position.strategy_mode,
        SignalLifecycle.trading_date == trading_day,
        SignalLifecycle.status == "BUY",
    ).order_by(SignalLifecycle.updated_at.desc()))
    if row is None:
        return
    row.status = "ENTERED"
    row.ended_at = position.opened_at
    row.valid_until = None
    row.reason = "Paper position entered after server-side setup recheck"
    row.updated_at = datetime.now(timezone.utc)
    _alert(db, lifecycle=row, symbol=position.symbol, event_type="ENTERED",
           message=f"{position.symbol} paper entry recorded after revalidation",
           payload={"position_id": position.id, "option_symbol": position.option_symbol})
    db.commit()


def expire_stale_lifecycles(db: Session, now: datetime) -> None:
    rows = list(db.scalars(select(SignalLifecycle).where(
        SignalLifecycle.status.in_(ACTIVE_STATES),
        SignalLifecycle.valid_until.is_not(None),
        SignalLifecycle.valid_until < _utc(now),
    )).all())
    for row in rows:
        row.status = "EXPIRED"
        row.ended_at = _utc(now)
        row.valid_until = None
        row.reason = f"{row.symbol} expired without another completed-candle verification"
        row.updated_at = datetime.now(timezone.utc)
        _alert(db, lifecycle=row, symbol=row.symbol, event_type="EXPIRED", message=row.reason,
               payload={"direction": row.direction, "status": "EXPIRED"})


def background_scan_once(*, now: datetime | None = None) -> None:
    """Scheduler entrypoint. The server, not an open browser, owns scanning."""
    global _BACKGROUND_PROVIDER
    scan_now = now or datetime.now(timezone.utc)
    with SessionLocal() as db:
        runtime = _runtime(db)
        runtime.heartbeat_at = scan_now
        if market_session(scan_now) != "regular":
            expire_stale_lifecycles(db, scan_now)
            close_lottery_trackers(db, scan_now)
            runtime.status = "idle_market_closed"
            runtime.last_error = None
            db.commit()
            return
        if _BACKGROUND_PROVIDER is None:
            _BACKGROUND_PROVIDER = get_provider()
        provider = _BACKGROUND_PROVIDER
        # Provider timestamps can remain at an after-hours startup value until the first request.
        # Use the scheduler clock for session ownership so the next market day cannot stay idle.
        trading_day = scan_now.astimezone(NY).date()
        flex = list(db.scalars(select(DailyWatchSymbol.symbol).where(
            DailyWatchSymbol.trading_date == trading_day).order_by(DailyWatchSymbol.id)).all())
        universe = list(dict.fromkeys(get_settings().parlay_symbol_list + flex))
        try:
            run_signal_scan(db, provider, universe,
                evaluation_at=latest_completed_candle_at(scan_now))
        except Exception:
            logger.exception("Background Parlay signal scan failed")
