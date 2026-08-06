from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

from app.market_data.cached import aggregate_candles
from app.schemas.market import CandleOut, OptionContractOut, ParlayCandidateOut
from app.services.contracts import annotate_chain
from app.services.indicators import spread_pct, vwap

NY = ZoneInfo("America/New_York")
STRATEGY_MODE: Literal["STRUCTURED_INTRADAY"] = "STRUCTURED_INTRADAY"
STRATEGY_VERSION = "structured-intraday-v1"
Direction = Literal["call", "put"]


@dataclass(frozen=True)
class StructuredEvaluation:
    direction: Direction | None
    status: Literal["BUY", "WATCH", "MISSED", "PASS"]
    score: float
    trigger: float
    stop: float
    target: float
    stretch_target: float
    extension_r: float
    reasons: list[str]
    rejection_reasons: list[str]


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _completed_bars(rows: list[CandleOut], minutes: int, completed_at: datetime) -> list[CandleOut]:
    boundary = _utc(completed_at)
    return [bar for bar in aggregate_candles(rows, minutes)
            if _utc(bar.timestamp) + timedelta(minutes=minutes) <= boundary + timedelta(minutes=1)]


def evaluate_structured_setup(candles: list[CandleOut], underlying_price: float,
                              completed_at: datetime) -> StructuredEvaluation:
    """Deterministic slower intraday model: 1H bias, 15M sweep, 5M shift, controlled retest."""
    rows = [row for row in candles if _utc(row.timestamp) <= _utc(completed_at)]
    if len(rows) < 60:
        return StructuredEvaluation(None, "PASS", 0, 0, 0, 0, 0, 0, [],
                                    ["Waiting for one full hour of session context"])
    bars_15 = _completed_bars(rows, 15, completed_at)
    bars_5 = _completed_bars(rows, 5, completed_at)
    if len(bars_15) < 4 or len(bars_5) < 12:
        return StructuredEvaluation(None, "PASS", 0, 0, 0, 0, 0, 0, [],
                                    ["Higher-timeframe candles are not complete"])

    hour_open = rows[-60].open
    hour_close = rows[-1].close
    session_vwap = vwap(rows)
    bullish_bias = hour_close > hour_open and bars_15[-1].close > session_vwap
    bearish_bias = hour_close < hour_open and bars_15[-1].close < session_vwap
    if bullish_bias == bearish_bias:
        return StructuredEvaluation(None, "PASS", 45, 0, 0, 0, 0, 0, [],
                                    ["1H direction and session VWAP do not agree"])
    direction: Direction = "call" if bullish_bias else "put"
    reasons = [f"1H price direction is {'bullish' if direction == 'call' else 'bearish'}",
               f"Price is {'above' if direction == 'call' else 'below'} session VWAP"]

    sweep_index: int | None = None
    for index in range(max(3, len(bars_15) - 3), len(bars_15)):
        prior = bars_15[max(0, index - 3):index]
        current = bars_15[index]
        if len(prior) < 3:
            continue
        if direction == "call":
            level = min(bar.low for bar in prior)
            swept = current.low < level and current.close > level
        else:
            level = max(bar.high for bar in prior)
            swept = current.high > level and current.close < level
        if swept:
            sweep_index = index
    if sweep_index is None:
        return StructuredEvaluation(direction, "PASS", 55, 0, 0, 0, 0, 0, reasons,
                                    ["No aligned 15M liquidity sweep"])

    sweep = bars_15[sweep_index]
    reasons.append(f"15M {'sell-side' if direction == 'call' else 'buy-side'} liquidity swept and reclaimed")
    bars_before = [bar for bar in bars_5 if bar.timestamp < sweep.timestamp][-3:]
    bars_after = [bar for bar in bars_5 if bar.timestamp >= sweep.timestamp]
    if len(bars_before) < 2 or not bars_after:
        return StructuredEvaluation(direction, "WATCH", 72, 0, sweep.low if direction == "call" else sweep.high,
                                    0, 0, 0, reasons, ["Waiting for a completed 5M structure shift"])
    trigger = (max(bar.high for bar in bars_before) if direction == "call"
               else min(bar.low for bar in bars_before))
    shifted = any(bar.close > trigger for bar in bars_after) if direction == "call" else any(
        bar.close < trigger for bar in bars_after)
    stop = sweep.low if direction == "call" else sweep.high
    risk = abs(trigger - stop)
    if risk <= 0:
        return StructuredEvaluation(direction, "PASS", 55, trigger, stop, 0, 0, 0, reasons,
                                    ["Structured invalidation produced no measurable risk"])
    target = trigger + (2 * risk if direction == "call" else -2 * risk)
    stretch = trigger + (3 * risk if direction == "call" else -3 * risk)
    extension = ((underlying_price - trigger) if direction == "call" else
                 (trigger - underlying_price)) / risk
    if not shifted:
        return StructuredEvaluation(direction, "WATCH", 76, trigger, stop, target, stretch,
                                    extension, reasons, ["Waiting for 5M market-structure shift"])
    reasons.append("5M market-structure shift confirmed")
    retest = 0 <= extension <= .75
    if extension > 1.25:
        return StructuredEvaluation(direction, "MISSED", 88, trigger, stop, target, stretch,
                                    extension, reasons, ["Move extended beyond the no-chase window"])
    if retest:
        reasons.append("Price remains inside the controlled retest window")
        return StructuredEvaluation(direction, "BUY", 92, trigger, stop, target, stretch,
                                    extension, reasons, [])
    return StructuredEvaluation(direction, "WATCH", 84, trigger, stop, target, stretch,
                                extension, reasons, ["Waiting for a controlled retest of the 5M break"])


def _expiration(provider: Any, symbol: str, trading_date: date) -> date | None:
    if not hasattr(provider, "expirations"):
        return None
    values = [value for value in provider.expirations(symbol)
              if 5 <= (value - trading_date).days <= 14]
    return min(values, key=lambda value: (abs((value - trading_date).days - 7), value)) if values else None


def _contract(chain: list[OptionContractOut], direction: Direction, target: float,
              underlying_price: float) -> tuple[OptionContractOut | None, list[str]]:
    rejection: set[str] = set()
    eligible: list[OptionContractOut] = []
    for contract in chain:
        if contract.right != direction:
            continue
        if not contract.actionable:
            rejection.add(contract.verification_reason)
            continue
        reachable = contract.strike <= target if direction == "call" else contract.strike >= target
        if not .50 <= contract.ask <= 5.00:
            rejection.add("Contract premium is outside the $50–$500 research range")
        elif spread_pct(contract.bid, contract.ask) > 15:
            rejection.add("Spread too wide")
        elif not reachable:
            rejection.add("Strike is beyond the 2R underlying target")
        else:
            eligible.append(contract)
    if not eligible:
        return None, sorted(rejection) or ["No liquid 5–14 DTE contract"]
    return min(eligible, key=lambda item: (abs(item.strike - underlying_price),
                                           spread_pct(item.bid, item.ask), -item.open_interest)), []


def _unavailable(symbol: str, reason: str, generated_at: datetime) -> ParlayCandidateOut:
    return ParlayCandidateOut(symbol=symbol, rank="PASS", direction="none", signal_status="UNAVAILABLE",
        score=0, score_label="PASS", unavailable_reason=reason,
        primary_action=f"UNAVAILABLE — {reason.upper()}", generated_at=generated_at,
        data_freshness="unavailable", strategy_mode=STRATEGY_MODE,
        strategy_version=STRATEGY_VERSION, timeframe_context="1H / 15M / 5M", target_dte="5–14 DTE")


def rank_structured_intraday(provider: Any, symbols: list[str], *,
                             completed_at: datetime) -> list[ParlayCandidateOut]:
    status = provider.status()
    if status.status == "unavailable":
        return [_unavailable(symbol, "Provider unavailable", status.latest_timestamp) for symbol in symbols]
    try:
        quotes = {quote.symbol: quote for quote in provider.quotes(symbols)}
    except (AttributeError, KeyError, TypeError, ValueError):
        quotes = {}
    output: list[ParlayCandidateOut] = []
    for symbol in symbols:
        quote = quotes.get(symbol)
        if quote is None:
            output.append(_unavailable(symbol, "Quote unavailable", status.latest_timestamp)); continue
        try:
            candles = provider.candles(symbol, "1m")
        except (AttributeError, KeyError, TypeError, ValueError):
            candles = []
        setup = evaluate_structured_setup(candles, quote.price, completed_at)
        base = dict(symbol=symbol, direction=setup.direction or "none", score=setup.score,
            score_label="PLAY" if setup.score >= 85 else "WATCH CLOSELY" if setup.score >= 70 else "PASS",
            underlying_price=quote.price, underlying_trigger=round(setup.trigger, 2) if setup.trigger else None,
            underlying_invalidation=round(setup.stop, 2) if setup.stop else None,
            first_underlying_target=round(setup.target, 2) if setup.target else None,
            stretch_underlying_target=round(setup.stretch_target, 2) if setup.stretch_target else None,
            reasons=setup.reasons, rejection_reasons=setup.rejection_reasons,
            generated_at=quote.timestamp, data_freshness=f"{status.mode}_current",
            strategy_mode=STRATEGY_MODE, strategy_version=STRATEGY_VERSION,
            timeframe_context="1H / 15M / 5M", target_dte="5–14 DTE")
        if setup.status in {"PASS", "WATCH"}:
            action = ("PASS — STRUCTURE NOT ALIGNED" if setup.status == "PASS" else
                      f"WAIT FOR {symbol} 5M CONFIRMATION / RETEST")
            output.append(ParlayCandidateOut(rank=base["score_label"], signal_status=setup.status,
                primary_action=action, **base)); continue
        if setup.status == "MISSED":
            output.append(ParlayCandidateOut(rank="PLAY", signal_status="MISSED",
                primary_action="MISSED — STRUCTURED MOVE ALREADY EXTENDED", **base)); continue

        trading_date = quote.timestamp.astimezone(NY).date()
        expiration = _expiration(provider, symbol, trading_date)
        if expiration is None:
            output.append(ParlayCandidateOut(rank="PASS", signal_status="PASS",
                primary_action="No verified 5–14 DTE contract available",
                contract_verification_reason="No expiration in the required 5–14 DTE window", **base)); continue
        try:
            raw_chain = provider.option_chain(symbol, expiration)
            chain = annotate_chain(raw_chain, symbol, provider.status().latest_timestamp,
                max_spread=15, min_volume=100, min_open_interest=500, min_dte=5, max_dte=14)
        except (KeyError, TypeError, ValueError):
            chain = []
        contract, rejection = _contract(chain, cast(Direction, setup.direction), setup.target, quote.price)
        if contract is None:
            output.append(ParlayCandidateOut(rank="PASS", signal_status="PASS",
                primary_action="No verified 5–14 DTE contract available",
                contract_verification_reason=rejection[0], **{**base, "rejection_reasons": rejection})); continue
        midpoint = round((contract.bid + contract.ask) / 2, 2)
        entry_high = round(min(contract.ask * 1.08, contract.ask + .15), 2)
        output.append(ParlayCandidateOut(rank="PLAY", signal_status="BUY", contract=contract,
            contract_cost=round(contract.ask * 100, 2), midpoint=midpoint,
            spread_percent=spread_pct(contract.bid, contract.ask), entry_low=midpoint,
            entry_high=entry_high, no_chase_price=round(contract.ask * 1.20, 2),
            first_option_target=round(entry_high * 1.5, 2), stretch_option_target=round(entry_high * 2.5, 2),
            primary_action=f"BUY BELOW ${entry_high:.2f}", contract_verification_status=contract.verification_status,
            contract_verification_reason=contract.verification_reason, actionable=contract.actionable, **base))
    order = {"BUY": 0, "WATCH": 1, "MISSED": 2, "PASS": 3, "UNAVAILABLE": 4}
    output.sort(key=lambda item: (order[item.signal_status], -item.score, item.symbol))
    for index, item in enumerate(output, 1): item.ranking_position = index
    return output
