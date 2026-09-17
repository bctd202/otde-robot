from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (AutomatedOptionMark, LiveWaitCandidate,
                           ParlayPaperPosition, SignalPerformance)
from app.schemas.market import OptionContractOut
from app.services.contracts import (is_verified_actionable_contract,
                                    validate_exit_quote)
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


def _completed_candles(provider, ticker: str, after: datetime, latest: datetime | None = None) -> list:
    """Return unseen, completed production-timeframe candles in chronological order."""
    latest = latest or _utc(provider.status().latest_timestamp)
    completion_boundary = latest - timedelta(minutes=1)
    return sorted(
        (candle for candle in provider.candles(ticker, PRODUCTION_TIMEFRAME)
         if _utc(candle.timestamp) > _utc(after) and _utc(candle.timestamp) <= completion_boundary),
        key=lambda candle: _utc(candle.timestamp),
    )


def _eastern_date(value: datetime) -> date:
    return _utc(value).astimezone(NY).date()


def analytics_exclusion_reason(row: SignalPerformance) -> str | None:
    """Return why a ledger row cannot support performance claims.

    This is deliberately derived rather than persisted so historical research rows
    stay intact and auditable.
    """
    if abs(row.entry_price - row.stop_price) <= 1e-9:
        return "ZERO_RISK"
    if row.exit_reason == "DATA_GAP":
        return "DATA_GAP"
    if row.result_r is not None and row.exit_at is not None and _eastern_date(row.exit_at) != row.trading_date:
        return "CROSS_SESSION_EXIT"
    return None


def deduplicate_positions(rows: list[SignalPerformance]) -> list[SignalPerformance]:
    """Keep the first actual BUY for each ticker and trading day.

    A quality-excluded first BUY still occupies that ticker-day. Selecting a later
    winner in its place would introduce survivorship bias.
    """
    selected: dict[tuple[date, str], SignalPerformance] = {}
    ordered = sorted(rows, key=lambda row: (_utc(row.triggered_at), row.signal_id))
    for row in ordered:
        if row.backend_status != "BUY":
            continue
        selected.setdefault((row.trading_date, row.ticker), row)
    return list(selected.values())


def _mark_data_gap(row: SignalPerformance, observed_at: datetime) -> None:
    row.exit_reason = "DATA_GAP"
    row.result_r = None
    row.result_return_pct = None
    row.exit_at = None
    row.exit_price = None
    row.duration_minutes = None
    row.updated_at = observed_at
    details = dict(row.condition_snapshot or {})
    details["analytics_data_quality"] = {
        "reason": "No completed same-session candle reached the 15:45 ET cutoff",
        "observed_at": observed_at.isoformat(),
    }
    row.condition_snapshot = details


def _record_option_entry(db: Session, row: SignalPerformance, contract: OptionContractOut,
                         observed_at: datetime) -> None:
    """Append the conservative entry ask for the first BUY per ticker/day."""
    if not get_settings().automated_option_shadow_enabled:
        return
    position_key = f"{row.trading_date.isoformat()}:{row.ticker.upper()}"
    if db.scalar(select(AutomatedOptionMark.id).where(
            AutomatedOptionMark.position_key == position_key)) is not None:
        return
    normalized = (contract.normalized_symbol or contract.option_symbol).strip().upper()
    db.add(AutomatedOptionMark(
        signal_id=row.signal_id, position_key=position_key, trading_date=row.trading_date,
        ticker=row.ticker, strategy_mode=row.strategy_mode, mark_type="ENTRY", mark_status="QUOTED",
        event_reason="AUTOMATED_BUY", event_at=_utc(row.triggered_at), observed_at=_utc(observed_at),
        option_symbol=contract.option_symbol, normalized_option_symbol=normalized,
        expiration=contract.expiration, strike=contract.strike, right=contract.right,
        bid=contract.bid, ask=contract.ask, last=contract.last, quote_timestamp=_utc(contract.timestamp),
        bid_timestamp=_utc(contract.bid_timestamp) if contract.bid_timestamp else None,
        ask_timestamp=_utc(contract.ask_timestamp) if contract.ask_timestamp else None,
        selected_price=contract.ask, price_basis="ASK", quote_lag_seconds=None,
        provider=contract.provider, data_mode=contract.data_mode,
        verification_status=contract.verification_status,
        verification_reason=contract.verification_reason, contract_multiplier=100,
        created_at=_utc(observed_at),
    ))
    db.flush()


def _option_chain(provider, ticker: str, expiration: date) -> list[OptionContractOut]:
    try:
        return provider.option_chain(ticker, expiration)
    except TypeError:
        return provider.option_chain(ticker)
    except (KeyError, ValueError, RuntimeError):
        return []


def _append_option_gap(db: Session, entry: AutomatedOptionMark, row: SignalPerformance,
                       observed_at: datetime, reason: str, provider_status) -> None:
    event_at = _utc(row.exit_at) if row.exit_at else _utc(observed_at)
    db.add(AutomatedOptionMark(
        signal_id=row.signal_id, position_key=None, trading_date=entry.trading_date,
        ticker=entry.ticker, strategy_mode=entry.strategy_mode, mark_type="EXIT",
        mark_status="OPTION_QUOTE_GAP", event_reason=row.exit_reason, event_at=event_at,
        observed_at=_utc(observed_at), option_symbol=entry.option_symbol,
        normalized_option_symbol=entry.normalized_option_symbol, expiration=entry.expiration,
        strike=entry.strike, right=entry.right, bid=None, ask=None, last=None,
        quote_timestamp=None, bid_timestamp=None, ask_timestamp=None, selected_price=None,
        price_basis="NONE", quote_lag_seconds=None, provider=provider_status.provider,
        data_mode=provider_status.mode, verification_status="unavailable",
        verification_reason=reason[:255], contract_multiplier=entry.contract_multiplier,
        created_at=_utc(observed_at),
    ))


def _record_option_exits(db: Session, provider, provider_status) -> None:
    """Append exact exit bids, retrying gaps until the bounded quote window ends."""
    settings = get_settings()
    if not settings.automated_option_shadow_enabled:
        return
    exited = set(db.scalars(select(AutomatedOptionMark.signal_id).where(
        AutomatedOptionMark.mark_type == "EXIT"
    )).all())
    entries = list(db.scalars(select(AutomatedOptionMark).where(
        AutomatedOptionMark.mark_type == "ENTRY"
    ).order_by(AutomatedOptionMark.event_at)).all())
    observed_at = _utc(provider_status.latest_timestamp)
    for entry in entries:
        if entry.signal_id in exited:
            continue
        row = db.get(SignalPerformance, entry.signal_id)
        if row is None or row.exit_reason == "OPEN":
            continue
        if row.exit_reason == "DATA_GAP" or row.exit_at is None:
            _append_option_gap(db, entry, row, observed_at,
                               "Underlying lifecycle ended without a defensible same-session exit event",
                               provider_status)
            continue

        event_at = _utc(row.exit_at)
        deadline = event_at + timedelta(seconds=settings.automated_option_max_quote_lag_seconds)
        reason = "Exact selected contract was absent from the Tradier chain response"
        chain: list[OptionContractOut] | None = None
        if hasattr(provider, "cached_option_chain"):
            chain = provider.cached_option_chain(entry.ticker, entry.expiration)
        if chain is None:
            can_request = (provider_status.provider == "tradier" and provider_status.mode == "live" and
                           provider_status.status == "healthy")
            if not can_request:
                reason = "Live Tradier exit data was unavailable"
            if can_request and hasattr(provider, "budget_status"):
                budget = provider.budget_status()
                remaining = budget.get("remaining")
                if remaining is not None and remaining <= settings.automated_option_request_reserve:
                    can_request = False
                    reason = "Tradier request reserve protected the scanner"
            if can_request:
                chain = _option_chain(provider, entry.ticker, entry.expiration)

        selected: OptionContractOut | None = None
        if chain is not None:
            expected = entry.normalized_option_symbol.strip().upper()
            selected = next((contract for contract in chain
                             if contract.option_symbol.strip().upper() == expected), None)
            if selected is not None:
                decision = validate_exit_quote(
                    selected, entry.ticker, expected, event_at,
                    settings.automated_option_max_quote_lag_seconds,
                )
                reason = decision.reason
                if decision.actionable:
                    assert selected.bid_timestamp is not None and selected.ask_timestamp is not None
                    bid_at = _utc(selected.bid_timestamp)
                    ask_at = _utc(selected.ask_timestamp)
                    db.add(AutomatedOptionMark(
                        signal_id=row.signal_id, position_key=None, trading_date=entry.trading_date,
                        ticker=entry.ticker, strategy_mode=entry.strategy_mode, mark_type="EXIT",
                        mark_status="QUOTED", event_reason=row.exit_reason, event_at=event_at,
                        observed_at=observed_at, option_symbol=selected.option_symbol,
                        normalized_option_symbol=expected, expiration=selected.expiration,
                        strike=selected.strike, right=selected.right, bid=selected.bid, ask=selected.ask,
                        last=selected.last, quote_timestamp=_utc(selected.timestamp),
                        bid_timestamp=bid_at, ask_timestamp=ask_at, selected_price=selected.bid,
                        price_basis="BID", quote_lag_seconds=max(0, round((bid_at-event_at).total_seconds())),
                        provider=selected.provider, data_mode=selected.data_mode,
                        verification_status="verified", verification_reason=decision.reason,
                        contract_multiplier=entry.contract_multiplier, created_at=observed_at,
                    ))
                    continue
        if observed_at >= deadline:
            _append_option_gap(db, entry, row, observed_at, reason, provider_status)


def evaluate_open_signals(db: Session, provider) -> None:
    """Continue durable outcomes without carrying an intraday trade overnight."""
    rows = db.scalars(select(SignalPerformance).where(
        SignalPerformance.source == "LIVE", SignalPerformance.exit_reason == "OPEN"
    )).all()
    provider_status = provider.status()
    latest = _utc(provider_status.latest_timestamp)
    for row in rows:
        cursor = row.last_evaluated_at or row.triggered_at
        for candle in _completed_candles(provider, row.ticker, cursor, latest):
            stamp = _utc(candle.timestamp)
            candle_day = stamp.astimezone(NY).date()
            if candle_day != row.trading_date:
                continue
            cutoff = stamp.astimezone(NY).time() >= SESSION_CUTOFF
            update_outcome(row, candle.high, candle.low, candle.close, stamp, cutoff=cutoff)
            row.last_evaluated_at = stamp
            if row.exit_reason != "OPEN":
                break
        cutoff_ready = datetime.combine(row.trading_date, SESSION_CUTOFF, NY) + timedelta(minutes=1)
        if (row.exit_reason == "OPEN" and provider_status.status == "healthy"
                and latest >= cutoff_ready.astimezone(timezone.utc)):
            _mark_data_gap(row, latest)
    _record_option_exits(db, provider, provider_status)
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
            entry = (candidate.underlying_trigger if candidate.underlying_trigger is not None
                     else candidate.underlying_price)
            stop = candidate.underlying_invalidation
            target = candidate.first_underlying_target
            if entry is None or stop is None or target is None or abs(entry - stop) <= 1e-9:
                continue
            contract = candidate.contract.model_dump(mode="json") if candidate.contract else None
            row = SignalPerformance(signal_id=str(uuid4()), source="LIVE", dedupe_key=dedupe_key,
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
                triggered_at=stamp, entry_price=entry, stop_price=stop, target_price=target,
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
                contract_option_type=candidate.contract.right if candidate.contract else None)
            db.add(row)
            db.flush()
            if candidate.signal_status == "BUY" and verified_contract and candidate.contract is not None:
                observed_at = provider_status.latest_timestamp if provider_status is not None else stamp
                _record_option_entry(db, row, candidate.contract, observed_at)
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


def option_shadow_results(db: Session, rows: list[SignalPerformance]) -> tuple[dict, dict[str, dict]]:
    """Return separately labeled ask-to-bid option evidence for selected ledger rows."""
    signal_ids = {row.signal_id for row in rows}
    marks = (list(db.scalars(select(AutomatedOptionMark).where(
        AutomatedOptionMark.signal_id.in_(signal_ids)
    ).order_by(AutomatedOptionMark.event_at, AutomatedOptionMark.id)).all()) if signal_ids else [])
    grouped: dict[str, dict[str, AutomatedOptionMark]] = {}
    for mark in marks:
        grouped.setdefault(mark.signal_id, {})[mark.mark_type] = mark

    payloads: dict[str, dict] = {}
    pnl_values: list[float] = []
    return_values: list[float] = []
    quoted = gaps = active = pending = 0
    for row in rows:
        pair = grouped.get(row.signal_id, {})
        entry, exit_mark = pair.get("ENTRY"), pair.get("EXIT")
        if entry is None:
            continue
        entry_cost = round(float(entry.selected_price or 0) * entry.contract_multiplier, 2)
        exit_value = pnl = return_pct = None
        if exit_mark is None:
            status = "ACTIVE" if row.exit_reason == "OPEN" else "EXIT_PENDING"
            active += status == "ACTIVE"
            pending += status == "EXIT_PENDING"
        elif exit_mark.mark_status == "QUOTED" and exit_mark.selected_price is not None:
            status = "CLOSED"
            exit_value = round(float(exit_mark.selected_price) * exit_mark.contract_multiplier, 2)
            pnl = round(exit_value-entry_cost, 2)
            return_pct = round(100*pnl/entry_cost, 2) if entry_cost else None
            pnl_values.append(pnl)
            if return_pct is not None:
                return_values.append(return_pct)
            quoted += 1
        else:
            status = "OPTION_QUOTE_GAP"
            gaps += 1
        payloads[row.signal_id] = {
            "status": status, "option_symbol": entry.normalized_option_symbol,
            "entry_ask": entry.selected_price, "entry_bid": entry.bid,
            "entry_quote_at": entry.quote_timestamp, "entry_cost_dollars": entry_cost,
            "exit_reason": exit_mark.event_reason if exit_mark else (
                row.exit_reason if row.exit_reason != "OPEN" else None),
            "exit_bid": exit_mark.selected_price if exit_mark and exit_mark.mark_status == "QUOTED" else None,
            "exit_ask": exit_mark.ask if exit_mark and exit_mark.mark_status == "QUOTED" else None,
            "exit_quote_at": exit_mark.quote_timestamp if exit_mark else None,
            "quote_lag_seconds": exit_mark.quote_lag_seconds if exit_mark else None,
            "exit_value_dollars": exit_value, "pnl_dollars": pnl, "return_percent": return_pct,
            "gap_reason": (exit_mark.verification_reason if exit_mark and
                           exit_mark.mark_status == "OPTION_QUOTE_GAP" else None),
            "entry_basis": "ASK", "exit_basis": "BID", "contract_multiplier": entry.contract_multiplier,
            "fees_modeled": False, "additional_slippage_modeled": False, "paper_only": True,
        }
    terminal = quoted + gaps
    summary = {
        "tracked_positions": len(payloads), "closed_with_quote": quoted, "quote_gaps": gaps,
        "active_positions": active, "exit_pending": pending,
        "untracked_selected_positions": max(0, len(rows)-len(payloads)),
        "quote_coverage_percent": round(100*quoted/terminal, 1) if terminal else 0,
        "wins": sum(value > 0 for value in pnl_values), "losses": sum(value < 0 for value in pnl_values),
        "cumulative_pnl_dollars": round(sum(pnl_values), 2),
        "average_pnl_dollars": round(sum(pnl_values)/len(pnl_values), 2) if pnl_values else 0,
        "average_return_percent": round(sum(return_values)/len(return_values), 2) if return_values else 0,
        "entry_basis": "Ask at automated BUY", "exit_basis": "First verified bid after underlying exit",
        "forward_only": True, "headline_metrics": False, "fees_modeled": False,
        "additional_slippage_modeled": False, "paper_only": True,
    }
    return summary, payloads


def performance_chart_data(rows: list[SignalPerformance], option_shadows: dict[str, dict]) -> dict:
    """Build compact, daily chart series without shipping the full ledger.

    Underlying-path results and ask-to-bid option evidence intentionally remain
    separate series. Quality-excluded rows stay visible in the outcome counts but
    never enter either underlying equity curve.
    """
    daily: dict[str, dict] = {}
    outcomes: dict[str, int] = {}
    ordered = sorted(rows, key=lambda row: (_utc(row.triggered_at), row.signal_id))
    for row in ordered:
        day = row.trading_date.isoformat()
        bucket = daily.setdefault(day, {
            "trading_date": day, "result_r": 0.0, "return_pct": 0.0,
            "resolved": 0, "wins": 0, "losses": 0,
            "option_pnl_dollars": 0.0, "option_closed": 0,
        })
        exclusion = analytics_exclusion_reason(row)
        outcome = "EXCLUDED" if exclusion is not None else row.exit_reason
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        if exclusion is None and row.exit_reason != "OPEN" and row.result_r is not None:
            result_r = float(row.result_r)
            if row.result_return_pct is not None:
                return_pct = float(row.result_return_pct)
            elif row.entry_price:
                return_pct = result_r * abs(row.entry_price-row.stop_price) / row.entry_price * 100
            else:
                return_pct = 0.0
            bucket["result_r"] += result_r
            bucket["return_pct"] += return_pct
            bucket["resolved"] += 1
            bucket["wins"] += result_r > 0
            bucket["losses"] += result_r < 0
        shadow = option_shadows.get(row.signal_id)
        if shadow and shadow.get("status") == "CLOSED" and shadow.get("pnl_dollars") is not None:
            bucket["option_pnl_dollars"] += float(shadow["pnl_dollars"])
            bucket["option_closed"] += 1

    cumulative_r = cumulative_return = cumulative_option = 0.0
    points = []
    for day in sorted(daily):
        bucket = daily[day]
        cumulative_r += bucket["result_r"]
        cumulative_return += bucket["return_pct"]
        cumulative_option += bucket["option_pnl_dollars"]
        points.append({
            **bucket,
            "result_r": round(bucket["result_r"], 3),
            "return_pct": round(bucket["return_pct"], 3),
            "option_pnl_dollars": round(bucket["option_pnl_dollars"], 2),
            "cumulative_r": round(cumulative_r, 3),
            "cumulative_return_pct": round(cumulative_return, 3),
            "cumulative_option_pnl_dollars": round(cumulative_option, 2),
        })
    outcome_order = ["TARGET", "STOP", "TIMED_EXIT", "OPEN", "EXCLUDED",
                     "DATA_GAP", "INVALIDATED", "MISSED"]
    labels = [label for label in outcome_order if label in outcomes]
    labels.extend(sorted(set(outcomes)-set(labels)))
    return {
        "daily": points,
        "outcomes": [{"outcome": label, "count": outcomes[label]} for label in labels],
    }


def market_movement_data(rows: list[SignalPerformance]) -> dict:
    """Describe saved underlying entry-to-exit moves without altering strategy R."""
    daily: dict[str, dict] = {}
    raw_moves: list[float] = []
    directional_moves: list[float] = []
    ordered = sorted(rows, key=lambda row: (_utc(row.triggered_at), row.signal_id))
    for row in ordered:
        if (analytics_exclusion_reason(row) is not None or row.exit_reason == "OPEN"
                or row.result_r is None or row.entry_price <= 0 or row.exit_price is None
                or row.direction not in {"CALL", "PUT"}):
            continue
        raw_move = (row.exit_price - row.entry_price) / row.entry_price * 100
        directional_move = raw_move if row.direction == "CALL" else -raw_move
        raw_moves.append(raw_move)
        directional_moves.append(directional_move)
        day = row.trading_date.isoformat()
        bucket = daily.setdefault(day, {
            "trading_date": day, "raw_move_pct": 0.0, "directional_move_pct": 0.0,
            "resolved": 0,
        })
        bucket["raw_move_pct"] += raw_move
        bucket["directional_move_pct"] += directional_move
        bucket["resolved"] += 1

    cumulative_raw = cumulative_directional = 0.0
    points = []
    for day in sorted(daily):
        bucket = daily[day]
        cumulative_raw += float(bucket["raw_move_pct"])
        cumulative_directional += float(bucket["directional_move_pct"])
        points.append({
            **bucket,
            "raw_move_pct": round(float(bucket["raw_move_pct"]), 3),
            "directional_move_pct": round(float(bucket["directional_move_pct"]), 3),
            "cumulative_raw_move_pct": round(cumulative_raw, 3),
            "cumulative_directional_move_pct": round(cumulative_directional, 3),
        })
    count = len(directional_moves)
    return {
        "resolved_with_prices": count,
        "average_directional_move_pct": round(sum(directional_moves) / count, 3) if count else 0,
        "positive_direction_rate": round(100 * sum(value > 0 for value in directional_moves) / count, 1)
        if count else 0,
        "cumulative_directional_move_pct": round(sum(directional_moves), 3),
        "net_raw_underlying_move_pct": round(sum(raw_moves), 3),
        "average_raw_underlying_move_pct": round(sum(raw_moves) / count, 3) if count else 0,
        "daily": points,
    }


def metrics(rows: list[SignalPerformance]) -> dict:
    eligible = [row for row in rows if analytics_exclusion_reason(row) is None]
    completed = sorted(
        (row for row in eligible if row.exit_reason != "OPEN" and row.result_r is not None),
        key=lambda row: (_utc(row.triggered_at), row.signal_id),
    )
    values = [float(row.result_r) for row in completed if row.result_r is not None]
    wins, losses = [value for value in values if value > 0], [value for value in values if value < 0]
    breakeven = [value for value in values if value == 0]
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
    quality_exclusions = sum(analytics_exclusion_reason(row) is not None for row in rows)
    exposure_ticker_days = len({(row.trading_date, row.ticker) for row in rows})
    return {"total_triggered_signals": len(rows), "resolved_signals": len(completed),
        "open_signals": sum(r.exit_reason == "OPEN" for r in eligible),
        "targets_hit": sum(r.exit_reason == "TARGET" for r in eligible),
        "stops_hit": sum(r.exit_reason == "STOP" for r in eligible),
        "timed_exits": sum(r.exit_reason == "TIMED_EXIT" for r in eligible),
        "invalidated_missed": sum(r.exit_reason in {"INVALIDATED", "MISSED"} for r in eligible),
        "data_gap_signals": sum(r.exit_reason == "DATA_GAP" for r in rows),
        "quality_exclusions": quality_exclusions,
        "wins": len(wins), "losses": len(losses), "breakeven": len(breakeven),
        "win_rate": round(100*len(wins)/len(completed), 1) if completed else 0,
        "average_r": round(sum(values)/len(values), 3) if values else 0, "cumulative_r": round(sum(values), 3),
        "profit_factor": round(sum(wins)/abs(sum(losses)), 2) if losses else None,
        "average_win_r": round(sum(wins)/len(wins), 3) if wins else 0,
        "average_loss_r": round(sum(losses)/len(losses), 3) if losses else 0,
        "maximum_drawdown_r": round(drawdown, 3),
        "average_return_pct": round(sum(returns)/len(returns), 3) if returns else 0,
        "cumulative_return_pct": round(sum(returns), 3),
        "maximum_drawdown_pct": round(return_drawdown, 3),
        "exposure_ticker_days": exposure_ticker_days,
        "exposure_minutes": sum(r.duration_minutes or 0 for r in completed),
        "average_duration": round(sum(r.duration_minutes or 0 for r in completed)/len(completed), 1) if completed else 0,
        "average_mfe": round(sum(r.mfe_r for r in completed)/len(completed), 3) if completed else 0,
        "average_mae": round(sum(r.mae_r for r in completed)/len(completed), 3) if completed else 0}
