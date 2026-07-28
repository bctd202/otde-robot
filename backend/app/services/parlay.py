"""Deterministic, paper-only Parlay candidate discovery and ranking."""

from collections import Counter
from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.market_data.base import MarketDataProvider
from app.schemas.market import OptionContractOut, ParlayCandidateOut, Quote, SignalStatus
from app.services.indicators import opening_range, spread_pct, vwap
from app.services.market_calendar import market_session

NY = ZoneInfo("America/New_York")


def clamp_parlay_score(value: float) -> int:
    return max(0, min(100, round(value)))


def score_category(score: int) -> str:
    if score >= 85:
        return "PLAY"
    if score >= 70:
        return "WATCH CLOSELY"
    if score >= 55:
        return "DEVELOPING"
    return "PASS"


def signal_status(score: int) -> SignalStatus:
    if score >= 85:
        return SignalStatus.BUY
    if score >= 55:
        return SignalStatus.WATCH
    return SignalStatus.PASS


def _unavailable(symbol: str, reason: str, timestamp: datetime) -> ParlayCandidateOut:
    return ParlayCandidateOut(
        rank=0, symbol=symbol, signal_status=SignalStatus.PASS,
        rejection_reasons=[reason], timestamp=timestamp, data_freshness="unavailable",
    )


def contract_rejections(contract: OptionContractOut, underlying: float, today) -> list[str]:
    reasons: list[str] = []
    if contract.expiration != today:
        reasons.append("expiration is not today")
    if contract.ask is None or not 0.20 <= contract.ask <= 1.00:
        reasons.append("no contract within price range")
    if contract.ask is not None and not 20 <= contract.ask * 100 <= 100:
        reasons.append("total debit outside $20-$100")
    if contract.bid is None or contract.bid <= 0:
        reasons.append("zero or missing bid")
    if contract.bid is not None and contract.ask is not None and spread_pct(contract.bid, contract.ask) > 20:
        reasons.append("spread too wide")
    if contract.volume is None or contract.volume < 250:
        reasons.append("current-day option volume below 250")
    reachable_distance = max(underlying * 0.012, 1.50)
    if abs(contract.strike - underlying) > reachable_distance:
        reasons.append("strike is beyond reachable underlying target")
    return reasons


def _candidate(
    provider_mode: str,
    quote: Quote,
    candles,
    contract: OptionContractOut,
) -> ParlayCandidateOut:
    current = quote.price
    current_vwap = vwap(candles)
    opening = opening_range(candles, 5)
    session_high = max(candle.high for candle in candles)
    session_low = min(candle.low for candle in candles)
    last = candles[-1]
    direction = "call" if contract.right == "call" else "put"
    bullish = direction == "call"
    confirmed = (
        last.close > current_vwap and last.close >= opening["high"]
        if bullish else last.close < current_vwap and last.close <= opening["low"]
    )
    aligned = last.close >= current_vwap if bullish else last.close <= current_vwap
    recent = candles[-6:-1]
    average_volume = sum(candle.volume for candle in recent) / len(recent) if recent else last.volume
    average_range = sum(candle.high - candle.low for candle in recent) / len(recent) if recent else 0
    accelerated = last.volume > average_volume and last.high - last.low >= average_range
    spread = spread_pct(contract.bid, contract.ask)  # eligibility guarantees both values
    first_target = session_high + max(current * 0.0025, 0.25) if bullish else session_low - max(current * 0.0025, 0.25)
    stretch_target = session_high + max(current * 0.006, 0.60) if bullish else session_low - max(current * 0.006, 0.60)
    invalidation = current_vwap - max(current * 0.0015, 0.15) if bullish else current_vwap + max(current * 0.0015, 0.15)
    trigger = max(last.high, opening["high"]) if bullish else min(last.low, opening["low"])
    risk = max(abs(trigger - invalidation), 0.01)
    reward_quality = abs(first_target - trigger) >= risk * 2
    ny_time = quote.timestamp.astimezone(NY).time()
    time_quality = time(9, 35) <= ny_time <= time(14, 30)

    components = [
        (25, confirmed, "underlying breakout/sweep/reclaim confirmed"),
        (15, aligned, "VWAP aligned"),
        (15, accelerated, "underlying price and volume accelerating"),
        (15, spread <= 20, "option bid/ask quality acceptable"),
        (10, (contract.volume or 0) >= 250, "current-day option volume qualifies"),
        (10, reward_quality, "reward to next underlying target qualifies"),
        (10, time_quality, "time-of-day quality acceptable"),
    ]
    score = clamp_parlay_score(sum(points for points, passed, _ in components if passed))
    reasons = [reason for _, passed, reason in components if passed]
    rejection_reasons = ["setup not confirmed"] if not confirmed else []
    ask = contract.ask or 0
    bid = contract.bid or 0
    midpoint = round((bid + ask) / 2, 2)
    return ParlayCandidateOut(
        rank=0, symbol=quote.symbol, direction=direction, contract_symbol=contract.option_symbol,
        strike=contract.strike, expiration=contract.expiration, bid=contract.bid, ask=contract.ask,
        midpoint=midpoint, total_debit=round(ask * 100, 2), spread_percent=spread,
        volume=contract.volume, open_interest=contract.open_interest,
        current_underlying_price=current, underlying_trigger=round(trigger, 2),
        underlying_invalidation=round(invalidation, 2), first_underlying_target=round(first_target, 2),
        stretch_underlying_target=round(stretch_target, 2), maximum_entry_premium=round(min(ask * 1.10, 1.0), 2),
        no_chase_premium=round(min(ask * 1.25, 1.25), 2), first_option_target=round(ask * 1.5, 2),
        stretch_option_target=round(ask * 2.5, 2), setup_score=score, score_category=score_category(score),
        signal_status=signal_status(score), reasons=reasons, rejection_reasons=rejection_reasons,
        timestamp=contract.timestamp, data_freshness=f"fresh_{provider_mode}",
    )


def rank_parlays(
    provider: MarketDataProvider,
    symbols: list[str],
    *,
    enforce_market_hours: bool = True,
) -> list[ParlayCandidateOut]:
    status = provider.status()
    now = status.latest_timestamp.astimezone(NY)
    if enforce_market_hours and market_session(now) != "regular":
        return [
            _unavailable(symbol, "market closed", now).model_copy(update={"rank": index})
            for index, symbol in enumerate(symbols, start=1)
        ]

    quote_by_symbol = {quote.symbol: quote for quote in provider.quotes(symbols)}
    results: list[ParlayCandidateOut] = []
    for symbol in symbols:
        quote = quote_by_symbol.get(symbol)
        if quote is None:
            results.append(_unavailable(symbol, "data unavailable", now))
            continue
        candles = provider.candles(symbol, "1m")
        if len(candles) < 6:
            results.append(_unavailable(symbol, "data unavailable", quote.timestamp))
            continue
        chain = provider.option_chain(symbol)
        if not chain:
            reason_getter = getattr(provider, "unavailable_reason", None)
            reason = reason_getter(symbol) if callable(reason_getter) else None
            results.append(_unavailable(symbol, reason or "no same-day expiration", quote.timestamp))
            continue

        eligible: list[ParlayCandidateOut] = []
        rejection_counts: Counter[str] = Counter()
        today = quote.timestamp.astimezone(NY).date()
        for contract in chain:
            rejections = contract_rejections(contract, quote.price, today)
            if rejections:
                rejection_counts.update(rejections)
                continue
            eligible.append(_candidate(status.mode, quote, candles, contract))
        if eligible:
            results.append(max(eligible, key=lambda item: (item.setup_score, item.volume or 0, item.open_interest or 0)))
        else:
            reason = rejection_counts.most_common(1)[0][0] if rejection_counts else "data unavailable"
            results.append(_unavailable(symbol, reason, quote.timestamp))

    results.sort(key=lambda item: (item.setup_score, item.volume or 0), reverse=True)
    return [item.model_copy(update={"rank": rank}) for rank, item in enumerate(results, start=1)]
