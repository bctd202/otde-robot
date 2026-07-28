from datetime import date

import httpx

from app.market_data.tradier import TradierMarketDataProvider


def test_tradier_normalizes_quotes_candles_expirations_and_chain():
    today = date.today().isoformat()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/quotes"):
            return httpx.Response(200, json={"quotes": {"quote": {
                "symbol": "SPY", "last": 550.25, "trade_date": 1_722_000_000_000,
            }}})
        if path.endswith("/timesales"):
            return httpx.Response(200, json={"series": {"data": [{
                "time": f"{today}T09:30:00", "open": 550, "high": 551,
                "low": 549.5, "close": 550.5, "volume": 1000,
            }]}})
        if path.endswith("/expirations"):
            return httpx.Response(200, json={"expirations": {"date": today}})
        return httpx.Response(200, json={"options": {"option": {
            "symbol": "SPY260101C00550000", "expiration_date": today,
            "strike": 550, "option_type": "call", "bid": .35, "ask": .40,
            "last": .38, "volume": 900, "open_interest": 2000,
            "trade_date": 1_722_000_000_000,
            "greeks": {"mid_iv": .2, "delta": .4, "gamma": .03, "theta": -.1, "vega": .02},
        }}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = TradierMarketDataProvider("secret", "https://example.test/v1", client)
    assert provider.quotes(["SPY"])[0].price == 550.25
    assert provider.candles("SPY")[0].volume == 1000
    assert provider.expirations("SPY") == [date.today()]
    contract = provider.option_chain("SPY")[0]
    assert contract.right == "call"
    assert contract.delta == .4
    assert provider.status().status == "healthy"


def test_tradier_fails_closed_without_token_or_on_http_error():
    missing = TradierMarketDataProvider(None, "https://example.test/v1")
    assert missing.quotes(["SPY"]) == []
    assert missing.status().status == "unavailable"

    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    failing = TradierMarketDataProvider("secret", "https://example.test/v1", client)
    assert failing.option_chain("SPY") == []
    assert "unavailable" in failing.status().message.lower()
