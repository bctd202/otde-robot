from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ParlayPaperPosition
from app.schemas.paper_positions import PaperPositionCreate, PaperPositionOut
from app.services.contracts import ACCEPTED_ACTIONABLE_DATA_MODES, is_verified_actionable_contract
from app.services.parlay import latest_completed_candle_at, rank_parlays
from app.services.structured_intraday import rank_structured_intraday

EASTERN = ZoneInfo("America/New_York")


def eastern_trading_date() -> date:
    """Return the calendar date used by the US options market."""
    return datetime.now(EASTERN).date()


def expire_if_past_expiration(db: Session, position: ParlayPaperPosition) -> bool:
    """Persist expiration without inventing a settlement or exit transaction."""
    if position.lifecycle_status == "ACTIVE" and position.expiration < eastern_trading_date():
        position.lifecycle_status = "EXPIRED"
        position.expired_at = datetime.now(timezone.utc)
        position.data_freshness = "historical_stale"
        db.commit()
        db.refresh(position)
        return True
    return position.lifecycle_status == "EXPIRED"


def management_decision(position: ParlayPaperPosition, option_price: float, underlying_price: float) -> tuple[str, str]:
    call = position.direction == "call"
    invalid = underlying_price < position.underlying_invalidation if call else underlying_price > position.underlying_invalidation
    runner = (option_price >= position.stretch_option_target or
              (underlying_price >= position.stretch_underlying_target if call else underlying_price <= position.stretch_underlying_target))
    first = (option_price >= position.first_option_target or
             (underlying_price >= position.first_underlying_target if call else underlying_price <= position.first_underlying_target))
    if invalid:
        return "EXIT", "EXIT — UNDERLYING INVALIDATION BREACHED"
    if runner:
        return "EXIT", "EXIT — RUNNER TARGET REACHED"
    if first:
        return "TAKE_PROFIT", "TAKE PROFIT — FIRST TARGET REACHED"
    side = "ABOVE" if call else "BELOW"
    return "HOLD", f"HOLD — SETUP REMAINS {side} INVALIDATION"


def create_position(db: Session, payload: PaperPositionCreate, provider: Any) -> ParlayPaperPosition:
    if payload.signal_status != "BUY":
        raise ValueError("Only qualified BUY candidates can be paper entered")
    status = provider.status()
    if status.provider != "tradier" or status.mode not in ACCEPTED_ACTIONABLE_DATA_MODES or status.status != "healthy":
        raise ValueError("Paper entry requires a verified current Tradier contract")
    symbol = payload.symbol.upper()
    # Never trust a BUY card that was rendered earlier. Re-run the complete
    # underlying setup and contract selection at click time on the server.
    completed_at = latest_completed_candle_at(status.latest_timestamp)
    ranked = (rank_structured_intraday(provider, [symbol], completed_at=completed_at)
              if payload.strategy_mode == "STRUCTURED_INTRADAY" else
              rank_parlays(provider, [symbol], completed_at=completed_at))
    candidate = next((item for item in ranked if item.symbol == symbol and
                      item.strategy_mode == payload.strategy_mode), None)
    if (candidate is None or candidate.signal_status != "BUY" or candidate.actionable is not True or
            candidate.contract is None or not is_verified_actionable_contract(candidate.contract)):
        raise ValueError("Setup expired or invalidated; refresh and wait for a new verified BUY")
    contract = candidate.contract
    if contract.option_symbol != payload.option_symbol:
        raise ValueError("The previously displayed option contract is no longer the verified selection")
    duplicate = db.scalar(select(ParlayPaperPosition).where(
        ParlayPaperPosition.option_symbol == payload.option_symbol,
        ParlayPaperPosition.lifecycle_status == "ACTIVE",
    ))
    if duplicate:
        raise ValueError("An active paper position already exists for this option symbol")
    if (contract.expiration != payload.expiration or contract.strike != payload.strike or
            contract.right != payload.direction):
        raise ValueError("Paper entry contract identity does not match the current Tradier chain")
    if candidate.underlying_price is None:
        raise ValueError("Paper entry requires a current server-derived underlying quote")
    server_now = datetime.now(timezone.utc)
    fill = contract.ask  # Server-derived current ask; never trust the browser snapshot.
    position = ParlayPaperPosition(
        symbol=contract.symbol.upper(), option_symbol=contract.option_symbol,
        direction=contract.right, strategy_mode=candidate.strategy_mode,
        strategy_version=candidate.strategy_version,
        expiration=contract.expiration, strike=contract.strike,
        quantity=1, entry_option_price=fill,
        entry_underlying_price=candidate.underlying_price,
        total_debit=round(fill * 100, 2), underlying_trigger=candidate.underlying_trigger,
        underlying_invalidation=candidate.underlying_invalidation,
        first_underlying_target=candidate.first_underlying_target,
        stretch_underlying_target=candidate.stretch_underlying_target,
        first_option_target=candidate.first_option_target,
        stretch_option_target=candidate.stretch_option_target, score=candidate.score,
        score_label=candidate.score_label, entry_reasons=candidate.reasons,
        provider_mode=status.mode, opened_at=server_now,
        lifecycle_status="ACTIVE", last_option_price=fill,
        last_underlying_price=candidate.underlying_price,
        last_marked_at=server_now, data_freshness="entry_snapshot",
        provenance_provider=contract.provider, provenance_data_mode=contract.data_mode,
        verification_status=contract.verification_status, verification_reason=contract.verification_reason,
        actionable=contract.actionable, original_occ_symbol=contract.option_symbol,
        normalized_option_symbol=contract.normalized_symbol, bid_timestamp=contract.bid_timestamp,
        ask_timestamp=contract.ask_timestamp, quote_timestamp=contract.timestamp,
    )
    db.add(position)
    db.commit()
    db.refresh(position)
    return position


def market_mark(position: ParlayPaperPosition, provider: Any) -> tuple[float | None, float | None, str]:
    status = provider.status()
    if status.mode != position.provider_mode or status.status == "unavailable":
        return None, None, "data_unavailable"
    try:
        quote = next((item for item in provider.quotes([position.symbol]) if item.symbol == position.symbol), None)
        try:
            chain = provider.option_chain(position.symbol, position.expiration)
        except TypeError:
            chain = provider.option_chain(position.symbol)
        contract = next((item for item in chain if item.option_symbol == position.option_symbol), None)
    except (KeyError, TypeError, ValueError):
        return None, None, "data_unavailable"
    if quote is None or contract is None:
        return None, None, "data_unavailable"
    # Bid is the defensible liquidation mark; never claim an unavailable midpoint.
    option_price = contract.bid if contract.bid > 0 else (contract.last if contract.last > 0 else None)
    if option_price is None:
        return None, None, "data_unavailable"
    return option_price, quote.price, f"{status.mode}_current"


def serialize(position: ParlayPaperPosition, *, option_price: float | None = None,
              underlying_price: float | None = None, freshness: str | None = None,
              market_data_available: bool = True) -> PaperPositionOut:
    closed = position.lifecycle_status == "CLOSED"
    expired = position.lifecycle_status == "EXPIRED"
    current_option = position.exit_option_price if closed else option_price
    current_underlying = position.exit_underlying_price if closed else underlying_price
    if closed:
        decision, action = "CLOSED", f"CLOSED — {position.exit_reason}"
    elif expired:
        decision, action = "EXPIRED", "EXPIRED — LAST-KNOWN PRICES ARE HISTORICAL; NO SETTLEMENT FABRICATED"
    elif not market_data_available or current_option is None or current_underlying is None:
        decision, action = "DATA_UNAVAILABLE", "DATA UNAVAILABLE — RETAINING LAST KNOWN POSITION STATE"
    else:
        decision, action = management_decision(position, current_option, current_underlying)
    unrealized = None if closed or expired or current_option is None else round((current_option - position.entry_option_price) * 100 * position.quantity, 2)
    realized = None if not closed or position.exit_option_price is None else round((position.exit_option_price - position.entry_option_price) * 100 * position.quantity, 2)
    pnl_price = position.exit_option_price if closed else (None if expired else current_option)
    pnl_percent = None if pnl_price is None else round((pnl_price - position.entry_option_price) / position.entry_option_price * 100, 2)
    return PaperPositionOut(
        id=position.id, symbol=position.symbol, option_symbol=position.option_symbol,
        direction=position.direction,
        strategy_mode=cast(Literal["ONE_MIN_0DTE", "STRUCTURED_INTRADAY"], position.strategy_mode),
        strategy_version=position.strategy_version,
        expiration=position.expiration, strike=position.strike,
        quantity=position.quantity, entry_option_price=position.entry_option_price,
        entry_underlying_price=position.entry_underlying_price, total_debit=position.total_debit,
        underlying_trigger=position.underlying_trigger,
        underlying_invalidation=position.underlying_invalidation,
        first_underlying_target=position.first_underlying_target,
        stretch_underlying_target=position.stretch_underlying_target,
        first_option_target=position.first_option_target,
        stretch_option_target=position.stretch_option_target, score=position.score,
        score_label=position.score_label, entry_reasons=position.entry_reasons,
        provider_mode=position.provider_mode, opened_at=position.opened_at,
        closed_at=position.closed_at, exit_option_price=position.exit_option_price,
        exit_underlying_price=position.exit_underlying_price, exit_reason=position.exit_reason,
        lifecycle_status=position.lifecycle_status, expired_at=position.expired_at,
        current_option_price=current_option,
        current_underlying_price=current_underlying, unrealized_pnl=unrealized,
        realized_pnl=realized, pnl_percent=pnl_percent,
        decision_status=cast(Literal["HOLD", "TAKE_PROFIT", "EXIT", "DATA_UNAVAILABLE", "EXPIRED", "CLOSED"], decision),
        data_freshness=freshness or position.data_freshness, next_action=action,
        last_marked_at=position.last_marked_at, paper_only=True,
        provenance_provider=position.provenance_provider, provenance_data_mode=position.provenance_data_mode,
        verification_status=position.verification_status, verification_reason=position.verification_reason,
actionable=bool(position.actionable), original_occ_symbol=position.original_occ_symbol,        normalized_option_symbol=position.normalized_option_symbol, bid_timestamp=position.bid_timestamp,
        ask_timestamp=position.ask_timestamp, quote_timestamp=position.quote_timestamp,
    )


def refresh_position(db: Session, position: ParlayPaperPosition, provider: Any) -> PaperPositionOut:
    if expire_if_past_expiration(db, position):
        return serialize(position, option_price=position.last_option_price,
                         underlying_price=position.last_underlying_price,
                         freshness="historical_stale", market_data_available=False)
    option_price, underlying_price, freshness = market_mark(position, provider)
    if option_price is not None and underlying_price is not None:
        position.last_option_price = option_price
        position.last_underlying_price = underlying_price
        position.last_marked_at = datetime.now(timezone.utc)
        position.data_freshness = freshness
        db.commit()
        return serialize(position, option_price=option_price, underlying_price=underlying_price,
                         freshness=freshness)
    # Retain the most recent mark for display and P&L, but keep the unavailable
    # decision explicit so stale values can never trigger management logic.
    return serialize(position, option_price=position.last_option_price,
                     underlying_price=position.last_underlying_price,
                     freshness=freshness, market_data_available=False)


def cached_position(position: ParlayPaperPosition, *, now: datetime | None = None) -> PaperPositionOut:
    """Serialize the server-owned mark without letting browser polling wake the provider."""
    if position.lifecycle_status != "ACTIVE":
        return serialize(position, option_price=position.last_option_price,
                         underlying_price=position.last_underlying_price)
    now = now or datetime.now(timezone.utc)
    marked = position.last_marked_at
    if marked is not None and marked.tzinfo is None:
        marked = marked.replace(tzinfo=timezone.utc)
    current = bool(marked and now - marked.astimezone(timezone.utc) <= timedelta(minutes=2)
                   and position.last_option_price is not None and position.last_underlying_price is not None)
    return serialize(position, option_price=position.last_option_price,
        underlying_price=position.last_underlying_price,
        freshness=position.data_freshness if current else "cached_stale",
        market_data_available=current)
