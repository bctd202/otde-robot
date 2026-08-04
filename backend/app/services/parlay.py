from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from app.schemas.market import CandleOut, OptionContractOut, ParlayCandidateOut
from app.services.indicators import opening_range, spread_pct, vwap

Direction = Literal["call", "put"]
SignalStatus = Literal["BUY", "WATCH", "MISSED", "PASS"]
NY = ZoneInfo("America/New_York")


def _score_label(score: float) -> Literal["PLAY", "WATCH CLOSELY", "DEVELOPING", "PASS"]:
    if score >= 85:
        return "PLAY"
    if score >= 70:
        return "WATCH CLOSELY"
    if score >= 55:
        return "DEVELOPING"
    return "PASS"


def _unavailable(symbol: str, reason: str, generated_at: Any) -> ParlayCandidateOut:
    return ParlayCandidateOut(symbol=symbol, rank="PASS", direction="none", signal_status="UNAVAILABLE",
        score=0, score_label="PASS", unavailable_reason=reason,
        primary_action=f"UNAVAILABLE — {reason.upper()}", generated_at=generated_at, data_freshness="unavailable",
        verification_reason=reason)


def _directional_plan(candles: list[CandleOut]) -> tuple[Direction | None, int, list[str], float, float, bool]:
    current = candles[-1]
    vw = vwap(candles)
    opening = opening_range(candles, 5)
    prior = candles[-8:-1]
    recent_high = max(c.high for c in prior)
    recent_low = min(c.low for c in prior)
    acceleration = (candles[-1].close - candles[-2].close) - (candles[-2].close - candles[-3].close)
    volume_rising = candles[-1].volume > sum(c.volume for c in candles[-4:-1]) / 3
    call_checks = [current.close > vw, candles[-2].close <= vw < current.close,
        current.close >= opening["high"], current.close > recent_high, acceleration > 0, volume_rising]
    put_checks = [current.close < vw, candles[-2].close >= vw > current.close,
        current.close <= opening["low"], current.close < recent_low, acceleration < 0, volume_rising]
    call_count, put_count = sum(call_checks), sum(put_checks)
    if max(call_count, put_count) < 3 or abs(call_count - put_count) < 2:
        return None, max(call_count, put_count), [], 0, 0, False
    direction: Direction = "call" if call_count > put_count else "put"
    checks = call_checks if direction == "call" else put_checks
    labels = (["Price above VWAP", "VWAP reclaimed", "Opening-range breakout", "Recent swing high cleared",
               "Positive price acceleration", "Underlying volume increasing"] if direction == "call" else
              ["Price below VWAP", "VWAP lost", "Opening-range breakdown", "Recent swing low cleared",
               "Negative price acceleration", "Underlying volume increasing"])
    trigger = max(opening["high"], recent_high) if direction == "call" else min(opening["low"], recent_low)
    invalidation = min(vw, opening["high"]) if direction == "call" else max(vw, opening["low"])
    confirmed = current.close > trigger if direction == "call" else current.close < trigger
    return direction, sum(checks), [label for label, passed in zip(labels, checks) if passed], trigger, invalidation, confirmed


def _eligible_contract(chain: list[OptionContractOut], direction: Direction, target: float) -> tuple[OptionContractOut | None, list[str]]:
    today = datetime.now(NY).date()
    rejection: set[str] = set()
    eligible = []
    for contract in chain:
        if contract.right != direction:
            continue
        spread = spread_pct(contract.bid, contract.ask)
        reachable = contract.strike <= target if direction == "call" else contract.strike >= target
        if contract.expiration != today:
            rejection.add("No same-day expiration")
        elif not 0.20 <= contract.ask <= 1.00:
            rejection.add("No contract between $20 and $100")
        elif contract.bid <= 0 or spread > 20:
            rejection.add("Spread too wide")
        elif contract.volume < 250:
            rejection.add("Option volume too low")
        elif not reachable:
            rejection.add("Strike is beyond the reachable target")
        else:
            eligible.append(contract)
    if not eligible:
        return None, sorted(rejection) or ["No qualifying same-day contract"]
    return max(eligible, key=lambda c: (c.volume + c.open_interest / 2, -spread_pct(c.bid, c.ask))), []


def rank_parlays(provider: Any, symbols: list[str]) -> list[ParlayCandidateOut]:
    """Build complete, deterministic paper-research plans without predicting outcomes."""
    provider_status = provider.status()
    output: list[ParlayCandidateOut] = []
    if provider_status.status == "unavailable":
        output = [_unavailable(symbol, "Provider unavailable", provider_status.latest_timestamp) for symbol in symbols]
        for position, candidate in enumerate(output, 1):
            candidate.ranking_position = position
        return output
    quotes = {}
    # Isolate quote requests so one malformed or unsupported symbol does not
    # prevent the rest of the universe from being evaluated.
    for requested_symbol in symbols:
        try:
            quotes.update(
                {quote.symbol: quote for quote in provider.quotes([requested_symbol])}
            )
        except (KeyError, TypeError, ValueError):
            continue
    for symbol in symbols:
        quote = quotes.get(symbol)
        if quote is None:
            output.append(_unavailable(symbol, "Quote unavailable", provider_status.latest_timestamp))
            continue
        try:
            candles, chain = provider.candles(symbol, "1m"), provider.option_chain(symbol)
        except (KeyError, TypeError, ValueError):
            candles, chain = [], []
        if len(candles) < 8:
            output.append(_unavailable(symbol, "Candles unavailable", quote.timestamp))
            continue
        direction, checks, reasons, trigger, invalidation, confirmed = _directional_plan(candles)
        if direction is None:
            output.append(ParlayCandidateOut(symbol=symbol, rank="PASS", direction="none", signal_status="PASS",
                score=min(54, 25 + checks * 6), score_label="PASS", underlying_price=quote.price,
                rejection_reasons=["Direction unclear", "Trigger not confirmed"],
                primary_action="PASS — TRIGGER NOT CONFIRMED", generated_at=quote.timestamp,
                data_freshness=f"{provider_status.mode}_current"))
            continue
        move = max(abs(trigger - invalidation), quote.price * .002)
        first_target = trigger + move * (1.5 if direction == "call" else -1.5)
        stretch_target = trigger + move * (2.5 if direction == "call" else -2.5)
        if not chain:
            chain_status = provider.status()
            reason = "Option chain unavailable" if chain_status.status == "unavailable" else "No listed expiration"
            output.append(ParlayCandidateOut(symbol=symbol, rank=_score_label(min(84, 42 + checks * 8)),
                direction=direction, signal_status="UNAVAILABLE", score=min(84, 42 + checks * 8),
                score_label=_score_label(min(84, 42 + checks * 8)), underlying_price=quote.price,
                underlying_trigger=round(trigger, 2), underlying_invalidation=round(invalidation, 2),
                first_underlying_target=round(first_target, 2), stretch_underlying_target=round(stretch_target, 2),
                reasons=reasons[:3], rejection_reasons=[reason], unavailable_reason=reason,
                primary_action="NO VERIFIED CONTRACT AVAILABLE", generated_at=quote.timestamp,
                data_freshness=f"{provider_status.mode}_current", provider=provider_status.provider,
                data_mode="mock" if provider_status.mode == "mock" else "unavailable",
                verification_reason=reason, actionable=False))
            continue
        contract, rejection = _eligible_contract(chain, direction, first_target)
        if contract is None:
            output.append(ParlayCandidateOut(symbol=symbol, rank="PASS", direction=direction, signal_status="PASS",
                score=min(54, 30 + checks * 4), score_label="PASS", underlying_price=quote.price,
                rejection_reasons=rejection, primary_action=f"PASS — {rejection[0].upper()}",
                generated_at=quote.timestamp, data_freshness=f"{provider_status.mode}_current"))
            continue
        midpoint = round((contract.bid + contract.ask) / 2, 2)
        preferred_entry = min(midpoint, contract.last) if contract.last > 0 else midpoint
        entry_low = round(preferred_entry, 2)
        entry_high = round(min(1.0, preferred_entry * 1.08), 2)
        no_chase = round(min(1.25, max(entry_high + .05, preferred_entry * 1.25)), 2)
        spread = spread_pct(contract.bid, contract.ask)
        extension = ((candles[-1].close - trigger) if direction == "call" else (trigger - candles[-1].close)) / move
        score = max(0, min(100, 42 + checks * 8 + min(contract.volume / 250, 8)
            + min(contract.open_interest / 1000, 4) - spread / 4))
        premium_exceeded = contract.ask > no_chase
        underlying_extended = extension > 1.35
        missed = confirmed and (premium_exceeded or underlying_extended)
        if missed:
            signal: SignalStatus = "MISSED"
        elif score >= 85 and confirmed and contract.ask <= entry_high and extension <= 1.35:
            signal = "BUY"
        elif score >= 70:
            signal = "WATCH"
        else:
            signal = "PASS"
        if signal == "PASS":
            output.append(ParlayCandidateOut(symbol=symbol, rank=_score_label(score), direction=direction,
                signal_status="PASS", score=round(score, 1), score_label=_score_label(score),
                underlying_price=quote.price, rejection_reasons=["Trigger not confirmed"],
                primary_action="PASS — TRIGGER NOT CONFIRMED", generated_at=quote.timestamp,
                data_freshness=f"{provider_status.mode}_current"))
            continue
        if signal == "BUY" and contract.actionable:
            action = f"BUY BELOW ${entry_high:.2f}"
        elif signal == "BUY":
            action = "NO VERIFIED CONTRACT AVAILABLE"
        elif signal == "MISSED":
            action = (f"MISSED — DO NOT CHASE ABOVE ${no_chase:.2f}" if premium_exceeded else
                "MISSED — UNDERLYING ALREADY EXTENDED")
        else:
            action = f"WAIT FOR {symbol} {'ABOVE' if direction == 'call' else 'BELOW'} ${trigger:.2f}"
        output.append(ParlayCandidateOut(symbol=symbol, rank=_score_label(score), direction=direction,
            signal_status=signal, score=round(score, 1), score_label=_score_label(score), underlying_price=quote.price,
            contract=contract, contract_cost=round(contract.ask * 100, 2), midpoint=midpoint, spread_percent=spread,
            entry_low=entry_low, entry_high=entry_high, no_chase_price=no_chase, underlying_trigger=round(trigger, 2),
            underlying_invalidation=round(invalidation, 2), first_underlying_target=round(first_target, 2),
            stretch_underlying_target=round(stretch_target, 2), first_option_target=round(entry_high * 2, 2),
            stretch_option_target=round(entry_high * 4, 2), reasons=reasons[:3], rejection_reasons=rejection,
            primary_action=action, generated_at=quote.timestamp, data_freshness=f"{provider_status.mode}_current",
            provider=contract.provider, data_mode=contract.data_mode, quote_freshness=contract.quote_freshness,
            verification_status=contract.verification_status, verification_reason=contract.verification_reason,
            actionable=contract.actionable))
    order = {"BUY": 0, "WATCH": 1, "MISSED": 2, "PASS": 3, "UNAVAILABLE": 4}
    output.sort(key=lambda item: (order[item.signal_status], -item.score, item.symbol))
    for position, candidate in enumerate(output, 1):
        candidate.ranking_position = position
    return output
