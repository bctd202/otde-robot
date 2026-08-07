from datetime import datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import LiveWaitCandidate, ParlayPaperPosition, SignalPerformance
from app.services.contracts import is_verified_actionable_contract
from app.services.parlay import PRODUCTION_TIMEFRAME

NY = ZoneInfo("America/New_York")
SESSION_CUTOFF = time(15, 45)
STRATEGY_VERSION = "parlay-v1"
STRATEGY_SNAPSHOT = {
    "engine": "app.services.parlay.evaluate_underlying_setup",
    "timeframe": PRODUCTION_TIMEFRAME,
    "session_cutoff_et": SESSION_CUTOFF.isoformat(timespec="minutes"),
    "paper_only": True,
}


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _completed_candles(provider, ticker: str, after: datetime) -> list:
    """Return unseen, completed production-timeframe candles in chronological order."""
    latest = _utc(provider.status().latest_timestamp)
    completion_boundary = latest - timedelta(minutes=1)
    return sorted(
        (candle for candle in provider.candles(ticker, PRODUCTION_TIMEFRAME)
         if _utc(candle.timestamp) > _utc(after) and _utc(candle.timestamp) <= completion_boundary),
        key=lambda candle: _utc(candle.timestamp),
    )


def evaluate_open_signals(db: Session, provider) -> None:
    """Continue durable live outcomes from the persisted candle cursor."""
    rows = db.scalars(select(SignalPerformance).where(
        SignalPerformance.source == "LIVE", SignalPerformance.exit_reason == "OPEN"
    )).all()
    for row in rows:
        cursor = row.last_evaluated_at or row.triggered_at
        for candle in _completed_candles(provider, row.ticker, cursor):
            stamp = _utc(candle.timestamp)
            cutoff = stamp.astimezone(NY).time() >= SESSION_CUTOFF
            update_outcome(row, candle.high, candle.low, candle.close, stamp, cutoff=cutoff)
            row.last_evaluated_at = stamp
            if row.exit_reason != "OPEN":
                break
    db.commit()


def track_candidates(db: Session, candidates: list, provider=None) -> None:
    now = datetime.now(timezone.utc)
    provider_status = provider.status() if provider is not None else None
    for candidate in candidates:
        verified_contract = (candidate.actionable is True and
                             is_verified_actionable_contract(candidate.contract))
        structured_underlying = (candidate.strategy_mode == "STRUCTURED_INTRADAY" and
            provider_status is not None and provider_status.provider == "tradier" and
            provider_status.mode == "live" and provider_status.status == "healthy" and
            candidate.signal_status in {"WATCH", "MISSED"})
        if (candidate.signal_status not in {"WATCH", "BUY", "MISSED"} or
                candidate.direction not in {"call", "put"} or
                not (verified_contract or structured_underlying)):
            continue
        stamp = _utc(candidate.generated_at)
        day = stamp.astimezone(NY).date()
        # Lifecycle ids represent distinct setup occurrences. Repeated scans of
        # one setup share an id, while a later same-symbol setup gets a new row.
        occurrence = candidate.lifecycle_id or stamp.isoformat()
        dedupe_key = f"{candidate.strategy_mode}:{candidate.symbol}:{candidate.direction}:{occurrence}"
        existing = db.scalar(select(SignalPerformance).where(
            SignalPerformance.source == "LIVE", SignalPerformance.dedupe_key == dedupe_key
        ))
        waiting = db.get(LiveWaitCandidate, dedupe_key)
        if existing is None and candidate.signal_status == "WATCH":
            if waiting is None:
                db.add(LiveWaitCandidate(key=dedupe_key, ticker=candidate.symbol,
                    direction=candidate.direction.upper(), strategy_mode=candidate.strategy_mode,
                    strategy_version=candidate.strategy_version, first_seen_at=stamp,
                    condition_snapshot={"reasons": candidate.reasons, "score": candidate.score,
                                        "setup_type": candidate.strategy_mode.lower()}))
            continue
        if existing is None and candidate.signal_status in {"BUY", "MISSED"}:
            contract = candidate.contract.model_dump(mode="json") if candidate.contract else None
            db.add(SignalPerformance(signal_id=str(uuid4()), source="LIVE", dedupe_key=dedupe_key,
                ticker=candidate.symbol, direction=candidate.direction.upper(), backend_status=candidate.signal_status,
                setup_type=("structured-liquidity" if candidate.strategy_mode == "STRUCTURED_INTRADAY"
                            else "directional-liquidity"), strategy_mode=candidate.strategy_mode,
                strategy_version=candidate.strategy_version,
                strategy_snapshot={**STRATEGY_SNAPSHOT, "strategy_mode": candidate.strategy_mode,
                                   "strategy_version": candidate.strategy_version,
                                   "timeframe_context": candidate.timeframe_context,
                                   "target_dte": candidate.target_dte},
                condition_snapshot={"reasons": candidate.reasons, "rejections": candidate.rejection_reasons},
                trading_date=day, first_wait_at=waiting.first_seen_at if waiting else None,
                triggered_at=stamp, entry_price=candidate.underlying_trigger or candidate.underlying_price,
                stop_price=candidate.underlying_invalidation, target_price=candidate.first_underlying_target,
                exit_reason="MISSED" if candidate.signal_status == "MISSED" else "OPEN", result_r=None,
                mfe_r=0, mae_r=0, score=candidate.score, user_entered=False, option_snapshot=contract,
                conservative_same_candle=False, created_at=now, updated_at=now, last_evaluated_at=stamp,
                provenance_provider=candidate.contract.provider if candidate.contract else provider_status.provider,
                provenance_data_mode=candidate.contract.data_mode if candidate.contract else provider_status.mode,
                verification_status=candidate.contract.verification_status if candidate.contract else "underlying_only",
                verification_reason=(candidate.contract.verification_reason if candidate.contract else
                                     "Structured setup missed before a contract entry was eligible"),
                actionable=candidate.contract.actionable if candidate.contract else False,
                original_occ_symbol=candidate.contract.option_symbol if candidate.contract else None,
                normalized_option_symbol=candidate.contract.normalized_symbol if candidate.contract else None,
                bid_timestamp=candidate.contract.bid_timestamp if candidate.contract else None,
                ask_timestamp=candidate.contract.ask_timestamp if candidate.contract else None,
                quote_timestamp=candidate.contract.timestamp if candidate.contract else None,
                contract_expiration=candidate.contract.expiration if candidate.contract else None,
                contract_strike=candidate.contract.strike if candidate.contract else None,
                contract_option_type=candidate.contract.right if candidate.contract else None))
    db.commit()
    if provider is not None:
        evaluate_open_signals(db, provider)


def update_outcome(row: SignalPerformance, high: float, low: float, close: float,
                   stamp: datetime, cutoff: bool = False) -> None:
    risk = abs(row.entry_price - row.stop_price)
    if not risk:
        return
    favorable = (high-row.entry_price)/risk if row.direction == "CALL" else (row.entry_price-low)/risk
    adverse = (row.entry_price-low)/risk if row.direction == "CALL" else (high-row.entry_price)/risk
    row.mfe_r = round(max(row.mfe_r, favorable), 4)
    row.mae_r = round(max(row.mae_r, adverse), 4)
    row.updated_at = _utc(stamp)
    target_hit = high >= row.target_price if row.direction == "CALL" else low <= row.target_price
    stop_hit = low <= row.stop_price if row.direction == "CALL" else high >= row.stop_price
    if target_hit and stop_hit:
        reason, price = "STOP", row.stop_price
        row.conservative_same_candle = True
    elif stop_hit:
        reason, price = "STOP", row.stop_price
    elif target_hit:
        reason, price = "TARGET", row.target_price
    elif cutoff:
        reason, price = "TIMED_EXIT", close
    else:
        return
    row.exit_reason, row.exit_price, row.exit_at = reason, price, _utc(stamp)
    signed = (price-row.entry_price) if row.direction == "CALL" else (row.entry_price-price)
    row.result_r = round(signed/risk, 4)
    row.result_return_pct = round(signed / row.entry_price * 100, 4) if row.entry_price else None
    row.duration_minutes = max(0, int((row.exit_at-_utc(row.triggered_at)).total_seconds()/60))


def link_paper_position(db: Session, position: ParlayPaperPosition) -> None:
    row = db.scalar(select(SignalPerformance).where(SignalPerformance.source == "LIVE",
        SignalPerformance.ticker == position.symbol,
        SignalPerformance.direction == position.direction.upper(),
        SignalPerformance.strategy_mode == position.strategy_mode,
        SignalPerformance.exit_reason == "OPEN")
        .order_by(SignalPerformance.triggered_at.desc()))
    if row:
        row.user_entered = True
        row.paper_position_id = position.id
        row.updated_at = datetime.now(timezone.utc)
        db.commit()


def metrics(rows: list[SignalPerformance]) -> dict:
    completed = [row for row in rows if row.exit_reason != "OPEN" and row.result_r is not None]
    values = [float(row.result_r) for row in completed if row.result_r is not None]
    wins, losses = [value for value in values if value > 0], [value for value in values if value < 0]
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak-equity)
    returns = []
    for row in completed:
        if row.result_return_pct is not None:
            returns.append(float(row.result_return_pct))
        elif row.result_r is not None and row.entry_price:
            returns.append(float(row.result_r) * abs(row.entry_price - row.stop_price) / row.entry_price * 100)
    return_equity = return_peak = return_drawdown = 0.0
    for value in returns:
        return_equity += value
        return_peak = max(return_peak, return_equity)
        return_drawdown = max(return_drawdown, return_peak - return_equity)
    return {"total_triggered_signals": len(rows), "open_signals": sum(r.exit_reason == "OPEN" for r in rows),
        "targets_hit": sum(r.exit_reason == "TARGET" for r in rows), "stops_hit": sum(r.exit_reason == "STOP" for r in rows),
        "timed_exits": sum(r.exit_reason == "TIMED_EXIT" for r in rows),
        "invalidated_missed": sum(r.exit_reason in {"INVALIDATED", "MISSED"} for r in rows),
        "win_rate": round(100*len(wins)/len(completed), 1) if completed else 0,
        "average_r": round(sum(values)/len(values), 3) if values else 0, "cumulative_r": round(sum(values), 3),
        "profit_factor": round(sum(wins)/abs(sum(losses)), 2) if losses else None,
        "maximum_drawdown_r": round(drawdown, 3),
        "average_return_pct": round(sum(returns)/len(returns), 3) if returns else 0,
        "cumulative_return_pct": round(sum(returns), 3),
        "maximum_drawdown_pct": round(return_drawdown, 3),
        "average_duration": round(sum(r.duration_minutes or 0 for r in completed)/len(completed), 1) if completed else 0,
        "average_mfe": round(sum(r.mfe_r for r in completed)/len(completed), 3) if completed else 0,
        "average_mae": round(sum(r.mae_r for r in completed)/len(completed), 3) if completed else 0}
