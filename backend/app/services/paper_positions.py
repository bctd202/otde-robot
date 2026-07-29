from datetime import datetime, timezone
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ParlayPaperPosition
from app.schemas.paper_positions import PaperPositionCreate, PaperPositionOut


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


def create_position(db: Session, payload: PaperPositionCreate) -> ParlayPaperPosition:
    duplicate = db.scalar(select(ParlayPaperPosition).where(
        ParlayPaperPosition.option_symbol == payload.option_symbol,
        ParlayPaperPosition.lifecycle_status == "ACTIVE",
    ))
    if duplicate:
        raise ValueError("An active paper position already exists for this option symbol")
    if payload.signal_status != "BUY":
        raise ValueError("Only qualified BUY candidates can be paper entered")
    fill = payload.option_ask  # New simulated entries always pay the displayed ask.
    position = ParlayPaperPosition(
        symbol=payload.symbol.upper(), option_symbol=payload.option_symbol,
        direction=payload.direction, expiration=payload.expiration, strike=payload.strike,
        quantity=1, entry_option_price=fill,
        entry_underlying_price=payload.underlying_entry_price,
        total_debit=round(fill * 100, 2), underlying_trigger=payload.underlying_trigger,
        underlying_invalidation=payload.underlying_invalidation,
        first_underlying_target=payload.first_underlying_target,
        stretch_underlying_target=payload.stretch_underlying_target,
        first_option_target=payload.first_option_target,
        stretch_option_target=payload.stretch_option_target, score=payload.score,
        score_label=payload.score_label, entry_reasons=payload.reasons,
        provider_mode=payload.provider_mode, opened_at=payload.entry_timestamp,
        lifecycle_status="ACTIVE", last_option_price=fill,
        last_underlying_price=payload.underlying_entry_price,
        last_marked_at=payload.entry_timestamp, data_freshness="entry_snapshot",
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
        contract = next((item for item in provider.option_chain(position.symbol)
                         if item.option_symbol == position.option_symbol), None)
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
              underlying_price: float | None = None, freshness: str | None = None) -> PaperPositionOut:
    closed = position.lifecycle_status == "CLOSED"
    current_option = position.exit_option_price if closed else option_price
    current_underlying = position.exit_underlying_price if closed else underlying_price
    if closed:
        decision, action = "CLOSED", f"CLOSED — {position.exit_reason}"
    elif current_option is None or current_underlying is None:
        decision, action = "DATA_UNAVAILABLE", "DATA UNAVAILABLE — RETAINING LAST KNOWN POSITION STATE"
    else:
        decision, action = management_decision(position, current_option, current_underlying)
    unrealized = None if closed or current_option is None else round((current_option - position.entry_option_price) * 100 * position.quantity, 2)
    realized = None if not closed or position.exit_option_price is None else round((position.exit_option_price - position.entry_option_price) * 100 * position.quantity, 2)
    pnl_price = position.exit_option_price if closed else current_option
    pnl_percent = None if pnl_price is None else round((pnl_price - position.entry_option_price) / position.entry_option_price * 100, 2)
    return PaperPositionOut(
        id=position.id, symbol=position.symbol, option_symbol=position.option_symbol,
        direction=position.direction, expiration=position.expiration, strike=position.strike,
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
        lifecycle_status=position.lifecycle_status, current_option_price=current_option,
        current_underlying_price=current_underlying, unrealized_pnl=unrealized,
        realized_pnl=realized, pnl_percent=pnl_percent,
        decision_status=cast(Literal["HOLD", "TAKE_PROFIT", "EXIT", "DATA_UNAVAILABLE", "CLOSED"], decision),
        data_freshness=freshness or position.data_freshness, next_action=action,
        last_marked_at=position.last_marked_at, paper_only=True,
    )


def refresh_position(db: Session, position: ParlayPaperPosition, provider: Any) -> PaperPositionOut:
    option_price, underlying_price, freshness = market_mark(position, provider)
    if option_price is not None and underlying_price is not None:
        position.last_option_price = option_price
        position.last_underlying_price = underlying_price
        position.last_marked_at = datetime.now(timezone.utc)
        position.data_freshness = freshness
        db.commit()
    return serialize(position, option_price=option_price, underlying_price=underlying_price, freshness=freshness)
