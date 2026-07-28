from typing import Any

from app.schemas.market import ParlayCandidateOut


def rank_parlays(provider: Any, symbols: list[str]) -> list[ParlayCandidateOut]:
    """Rank affordable 0DTE contracts using deterministic liquidity/momentum rules."""
    quotes = {}
    # Isolate symbols so one malformed or unsupported upstream row cannot turn
    # another symbol into a candidate or take down the complete scan.
    for requested_symbol in symbols:
        try:
            quotes.update({quote.symbol: quote for quote in provider.quotes([requested_symbol])})
        except (KeyError, TypeError, ValueError):
            continue
    output = []
    for symbol in symbols:
        quote = quotes.get(symbol)
        if quote is None:
            output.append(ParlayCandidateOut(symbol=symbol, rank="PASS", score=0,
                unavailable_reason="Quote unavailable; candidate was not evaluated."))
            continue
        try:
            candles = provider.candles(symbol, "1m")
            chain = provider.option_chain(symbol)
        except (KeyError, TypeError, ValueError):
            candles, chain = [], []
        affordable = [c for c in chain if 0.20 <= c.ask <= 1.00 and c.bid > 0]
        if not candles:
            reason = "Same-day candles unavailable; candidate was not evaluated."
        elif not chain:
            reason = "Same-day option chain unavailable; candidate was not evaluated."
        elif not affordable:
            reason = "No same-day contract has a $20–$100 ask cost and positive bid."
        else:
            reason = None
        if reason:
            output.append(ParlayCandidateOut(symbol=symbol, rank="PASS", score=0,
                underlying_price=quote.price, unavailable_reason=reason))
            continue
        bullish = candles[-1].close > candles[0].open
        preferred = "call" if bullish else "put"
        choices = [c for c in affordable if c.right == preferred] or affordable
        contract = max(choices, key=lambda c: (
            min(c.volume, 2000) + min(c.open_interest, 5000) / 2
            - ((c.ask - c.bid) / c.ask * 2000), -c.ask
        ))
        spread = (contract.ask - contract.bid) / contract.ask
        momentum = abs(candles[-1].close - candles[0].open) / quote.price * 100
        score = max(0.0, min(100.0, 35 + min(momentum * 25, 25)
            + min(contract.volume / 100, 15) + min(contract.open_interest / 500, 15)
            - spread * 30))
        rank = "PLAY" if score >= 75 else "WATCH" if score >= 60 else "DEVELOPING" if score >= 45 else "PASS"
        output.append(ParlayCandidateOut(symbol=symbol, rank=rank, score=round(score, 1),
            underlying_price=quote.price, contract=contract, contract_cost=round(contract.ask * 100, 2),
            reasons=[f"{preferred.title()} selected from intraday direction.",
                     f"Volume {contract.volume}; open interest {contract.open_interest}.",
                     f"Bid-ask spread {spread:.1%}."]))
    order = {"PLAY": 0, "WATCH": 1, "DEVELOPING": 2, "PASS": 3}
    return sorted(output, key=lambda item: (order[item.rank], -item.score, item.symbol))
