from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import LotteryQuoteSnapshot, LotteryTracker
from app.schemas.market import LotteryOut, OptionContractOut, Quote
from app.services.contracts import annotate_chain
from app.services.indicators import spread_pct
from app.services.setup_engine import lottery_candidates

NY = ZoneInfo("America/New_York")


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _observed_at(evaluation_at: datetime) -> datetime:
    """Name each point for the minute immediately after its completed evaluation candle."""
    return _utc(evaluation_at).replace(second=0, microsecond=0) + timedelta(minutes=1)


def _chain(provider, symbol: str, trading_day: date) -> list[OptionContractOut]:
    try:
        return provider.option_chain(symbol, trading_day)
    except TypeError:
        return provider.option_chain(symbol)
    except (KeyError, ValueError):
        return []


def _market_inputs(provider, symbols: list[str], trading_day: date, observed_at: datetime,
                   evaluation_at: datetime) -> tuple[
                       dict[str, Quote], dict[str, list], dict[str, list[OptionContractOut]]
                   ]:
    try:
        quotes = {quote.symbol.upper(): quote for quote in provider.quotes(symbols)}
    except (KeyError, TypeError, ValueError):
        quotes = {}
    candles: dict[str, list] = {}
    chains: dict[str, list[OptionContractOut]] = {}
    for symbol in symbols:
        try:
            rows = provider.candles(symbol, "1m")
        except (KeyError, TypeError, ValueError):
            rows = []
        candles[symbol] = [row for row in rows if _utc(row.timestamp) <= _utc(evaluation_at)]
        raw_chain = _chain(provider, symbol, trading_day)
        chains[symbol] = annotate_chain(raw_chain, symbol, observed_at) if raw_chain else []
    return quotes, candles, chains


def _discover(symbols: list[str], quotes: dict[str, Quote], candles: dict[str, list],
              chains: dict[str, list[OptionContractOut]], provider_status) -> list[LotteryOut]:
    candidates: list[LotteryOut] = []
    for symbol in symbols:
        quote = quotes.get(symbol)
        rows = candles.get(symbol, [])
        if quote is None or len(rows) < 12:
            continue
        candidates.extend(lottery_candidates(symbol, rows, quote, chains.get(symbol, []), provider_status))
    return sorted(candidates, key=lambda item: item.setup_score, reverse=True)[:3]


def _contract_map(chains: dict[str, list[OptionContractOut]]) -> dict[str, OptionContractOut]:
    output: dict[str, OptionContractOut] = {}
    for chain in chains.values():
        for contract in chain:
            output[contract.option_symbol.strip().upper()] = contract
            if contract.normalized_symbol:
                output[contract.normalized_symbol.strip().upper()] = contract
    return output


def _new_tracker(candidate: LotteryOut, quote: Quote, trading_day: date,
                 observed_at: datetime) -> LotteryTracker:
    option_symbol = candidate.option_symbol.strip().upper()
    return LotteryTracker(
        id=str(uuid4()), trading_date=trading_day, symbol=candidate.symbol.upper(),
        option_symbol=option_symbol,
        normalized_option_symbol=(candidate.normalized_symbol or option_symbol).strip().upper(),
        expiration=candidate.expiration, right=candidate.right, strike=candidate.strike,
        status="ACTIVE", first_seen_at=observed_at, last_qualified_at=observed_at,
        entry_ask=candidate.ask, entry_bid=candidate.bid,
        entry_underlying_price=quote.price, setup_score=candidate.setup_score,
        initial_snapshot=candidate.model_dump(mode="json"), provider=candidate.provider,
        data_mode=candidate.data_mode, verification_status=candidate.verification_status,
        verification_reason=candidate.verification_reason, actionable=candidate.actionable,
        peak_bid=0, created_at=observed_at, updated_at=observed_at,
    )


def _record_point(db: Session, tracker: LotteryTracker, contract: OptionContractOut,
                  underlying: Quote | None, candidate: LotteryOut | None,
                  observed_at: datetime) -> None:
    exists = db.scalar(select(LotteryQuoteSnapshot.id).where(
        LotteryQuoteSnapshot.tracker_id == tracker.id,
        LotteryQuoteSnapshot.observed_at == observed_at,
    ))
    if exists is not None:
        return
    midpoint = round((contract.bid + contract.ask) / 2, 4)
    qualified = candidate is not None
    db.add(LotteryQuoteSnapshot(
        tracker_id=tracker.id, observed_at=observed_at,
        quote_timestamp=_utc(contract.timestamp),
        bid_timestamp=_utc(contract.bid_timestamp) if contract.bid_timestamp else None,
        ask_timestamp=_utc(contract.ask_timestamp) if contract.ask_timestamp else None,
        bid=contract.bid, ask=contract.ask, midpoint=midpoint, last=contract.last,
        underlying_price=underlying.price if underlying else None,
        spread_percent=spread_pct(contract.bid, contract.ask),
        volume=contract.volume, open_interest=contract.open_interest,
        delta=contract.delta, gamma=contract.gamma, theta=contract.theta, iv=contract.iv,
        is_qualified=qualified, setup_score=candidate.setup_score if candidate else None,
    ))
    tracker.last_quote_at = observed_at
    tracker.latest_bid = contract.bid
    tracker.latest_ask = contract.ask
    tracker.latest_midpoint = midpoint
    tracker.latest_last = contract.last
    tracker.latest_underlying_price = underlying.price if underlying else None
    tracker.updated_at = observed_at
    if qualified:
        tracker.last_qualified_at = observed_at
    if contract.bid > tracker.peak_bid:
        tracker.peak_bid = contract.bid
        tracker.peak_bid_at = observed_at
    if tracker.entry_ask > 0:
        if tracker.hit_2x_at is None and contract.bid >= tracker.entry_ask * 2:
            tracker.hit_2x_at = observed_at
        if tracker.hit_5x_at is None and contract.bid >= tracker.entry_ask * 5:
            tracker.hit_5x_at = observed_at
        if tracker.hit_10x_at is None and contract.bid >= tracker.entry_ask * 10:
            tracker.hit_10x_at = observed_at


def track_lottery_scan(db: Session, provider, symbols: list[str], evaluation_at: datetime) -> list[LotteryTracker]:
    """Persist the displayed lotto shortlist, then mark every active contract once per scan."""
    observed_at = _observed_at(evaluation_at)
    trading_day = observed_at.astimezone(NY).date()
    close_lottery_trackers(db, observed_at)
    requested_symbols = list(dict.fromkeys(symbol.upper() for symbol in symbols))
    active = list(db.scalars(select(LotteryTracker).where(
        LotteryTracker.status == "ACTIVE",
    )).all())
    all_symbols = list(dict.fromkeys(requested_symbols + [row.symbol for row in active]))
    quotes, candles, chains = _market_inputs(
        provider, all_symbols, trading_day, observed_at, evaluation_at,
    )
    candidates = _discover(requested_symbols, quotes, candles, chains, provider.status())
    candidate_by_contract = {item.option_symbol.strip().upper(): item for item in candidates}

    trackers_by_contract = {
        row.option_symbol.strip().upper(): row for row in active if row.trading_date == trading_day
    }
    for candidate in candidates:
        key = candidate.option_symbol.strip().upper()
        tracker = trackers_by_contract.get(key)
        if tracker is None:
            tracker = db.scalar(select(LotteryTracker).where(
                LotteryTracker.trading_date == trading_day,
                LotteryTracker.option_symbol == key,
            ))
        quote = quotes.get(candidate.symbol.upper())
        if tracker is None and quote is not None:
            tracker = _new_tracker(candidate, quote, trading_day, observed_at)
            db.add(tracker)
            db.flush()
        if tracker is not None:
            trackers_by_contract[key] = tracker

    contracts = _contract_map(chains)
    tracked = list(db.scalars(select(LotteryTracker).where(
        LotteryTracker.status == "ACTIVE",
        LotteryTracker.trading_date == trading_day,
    ).order_by(LotteryTracker.first_seen_at)).all())
    for tracker in tracked:
        key = tracker.option_symbol.strip().upper()
        normalized = (tracker.normalized_option_symbol or key).strip().upper()
        contract = contracts.get(normalized) or contracts.get(key)
        if contract is None:
            continue
        _record_point(db, tracker, contract, quotes.get(tracker.symbol),
                      candidate_by_contract.get(key), observed_at)
    db.flush()
    return tracked


def close_lottery_trackers(db: Session, now: datetime) -> int:
    """Freeze active rows after their regular session; the last scan remains the last observed quote."""
    local_now = _utc(now).astimezone(NY)
    rows = list(db.scalars(select(LotteryTracker).where(
        LotteryTracker.status == "ACTIVE",
    )).all())
    closed = 0
    for row in rows:
        session_finished = row.trading_date < local_now.date() or (
            row.trading_date == local_now.date() and local_now.time() >= time(16, 0)
        )
        if not session_finished:
            continue
        row.status = "CLOSED"
        row.closed_at = _utc(now)
        row.updated_at = _utc(now)
        closed += 1
    return closed


def tracker_points(db: Session, tracker_id: str) -> list[LotteryQuoteSnapshot]:
    return list(db.scalars(select(LotteryQuoteSnapshot).where(
        LotteryQuoteSnapshot.tracker_id == tracker_id,
    ).order_by(LotteryQuoteSnapshot.observed_at, LotteryQuoteSnapshot.id)).all())


def serialize_tracker(row: LotteryTracker, points: list[LotteryQuoteSnapshot]) -> dict:
    entry = row.entry_ask
    latest_multiple = row.latest_bid / entry if row.latest_bid is not None and entry > 0 else None
    peak_multiple = row.peak_bid / entry if entry > 0 else 0
    latest_point = points[-1] if points else None
    return {
        "id": row.id, "trading_date": row.trading_date, "symbol": row.symbol,
        "option_symbol": row.option_symbol, "expiration": row.expiration,
        "right": row.right, "strike": row.strike, "status": row.status,
        "first_seen_at": row.first_seen_at, "last_qualified_at": row.last_qualified_at,
        "last_quote_at": row.last_quote_at, "closed_at": row.closed_at,
        "entry_ask": row.entry_ask, "entry_bid": row.entry_bid,
        "entry_cost": round(row.entry_ask * 100, 2),
        "entry_underlying_price": row.entry_underlying_price,
        "setup_score": row.setup_score, "latest_bid": row.latest_bid,
        "latest_ask": row.latest_ask,
        "latest_sellable_value": round(row.latest_bid * 100, 2) if row.latest_bid is not None else None,
        "latest_multiple": round(latest_multiple, 3) if latest_multiple is not None else None,
        "latest_return_percent": round((latest_multiple - 1) * 100, 1) if latest_multiple is not None else None,
        "peak_bid": row.peak_bid, "peak_sellable_value": round(row.peak_bid * 100, 2),
        "peak_multiple": round(peak_multiple, 3),
        "peak_return_percent": round((peak_multiple - 1) * 100, 1),
        "peak_bid_at": row.peak_bid_at, "hit_2x_at": row.hit_2x_at,
        "hit_5x_at": row.hit_5x_at, "hit_10x_at": row.hit_10x_at,
        "point_count": len(points),
        "currently_qualified": bool(latest_point and latest_point.is_qualified),
        "provider": row.provider, "data_mode": row.data_mode,
        "verification_status": row.verification_status,
        "verification_reason": row.verification_reason, "actionable": row.actionable,
    }


def serialize_point(row: LotteryQuoteSnapshot) -> dict:
    return {
        "observed_at": row.observed_at, "quote_timestamp": row.quote_timestamp,
        "bid_timestamp": row.bid_timestamp, "ask_timestamp": row.ask_timestamp,
        "bid": row.bid, "ask": row.ask, "midpoint": row.midpoint, "last": row.last,
        "bid_value": round(row.bid * 100, 2), "ask_value": round(row.ask * 100, 2),
        "underlying_price": row.underlying_price, "spread_percent": row.spread_percent,
        "is_qualified": row.is_qualified, "setup_score": row.setup_score,
    }
