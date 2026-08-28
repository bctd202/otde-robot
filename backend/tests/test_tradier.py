from datetime import date, datetime, timezone
import logging

import httpx

from app.core.config import get_settings
from app.market_data.tradier import TradierMarketDataProvider, _latest_available_market_date


def test_tradier_normalizes_quotes_candles_expirations_and_chain():
    expiration = date(2026, 1, 15)
    expiration_text = expiration.isoformat()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/quotes"):
            return httpx.Response(200, json={"quotes": {"quote": {
                "symbol": "SPY", "last": 550.25, "trade_date": 1_722_000_000_000,
            }}})
        if path.endswith("/timesales"):
            assert request.url.params["start"] == f"{expiration_text} 09:30"
            return httpx.Response(200, json={"series": {"data": [{
                "time": f"{expiration_text}T09:30:00", "open": 550, "high": 551,
                "low": 549.5, "close": 550.5, "volume": 1000,
            }]}})
        if path.endswith("/expirations"):
            return httpx.Response(200, json={"expirations": {"date": expiration_text}})
        return httpx.Response(200, json={"options": {"option": {
            "symbol": "SPY260115C00550000", "expiration_date": expiration_text,
            "strike": 550, "option_type": "call", "bid": .35, "ask": .40,
            "last": .38, "volume": 900, "open_interest": 2000,
            "trade_date": 1_722_000_000_000,
            "bid_date": 1_722_000_000_000, "ask_date": 1_722_000_000_000,
            "greeks": {"mid_iv": .2, "delta": .4, "gamma": .03, "theta": -.1, "vega": .02},
        }}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = TradierMarketDataProvider(
        "secret", "https://example.test/v1", client, trading_date=expiration, data_mode="live"
    )
    assert provider.quotes(["SPY"])[0].price == 550.25
    assert provider.candles("SPY")[0].volume == 1000
    assert provider.expirations("SPY") == [expiration]
    contract = provider.option_chain("SPY")[0]
    assert contract.right == "call"
    assert contract.delta == .4
    assert provider.status().status == "healthy"


def test_latest_available_market_date_uses_new_york_session_calendar():
    utc_rollover = datetime(2026, 8, 28, 2, 12, tzinfo=timezone.utc)
    assert _latest_available_market_date(now=utc_rollover) == date(2026, 8, 27)

    premarket = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
    assert _latest_available_market_date(now=premarket) == date(2026, 8, 28)

    july_fourth_weekend = datetime(2026, 7, 4, 14, 0, tzinfo=timezone.utc)
    assert _latest_available_market_date(now=july_fourth_weekend) == date(2026, 7, 2)

    assert _latest_available_market_date(date(2026, 7, 3)) == date(2026, 7, 2)


def test_tradier_fails_closed_without_token_or_on_http_error():
    unused_client = httpx.Client(transport=httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(AssertionError("must not request without a token"))))
    missing = TradierMarketDataProvider(None, "https://example.test/v1", unused_client)
    assert missing.quotes(["SPY"]) == []
    assert missing.status().status == "unavailable"

    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    failing = TradierMarketDataProvider("secret", "https://example.test/v1", client, data_mode="live")
    assert failing.option_chain("SPY") == []
    assert failing.status().message == "Tradier data unavailable: HTTP 503."


def test_tradier_hard_budget_stops_upstream_calls_before_documented_limit(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "tradier_request_budget_per_minute", 2)
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        symbol = request.url.params.get("symbols", "SPY")
        return httpx.Response(200, headers={"X-Ratelimit-Allowed": "120",
            "X-Ratelimit-Used": str(requests), "X-Ratelimit-Available": str(120 - requests)},
            json={"quotes": {"quote": {"symbol": symbol, "last": 100,
                  "trade_date": 1_722_000_000_000}}})

    provider = TradierMarketDataProvider("secret", "https://example.test/v1",
        httpx.Client(transport=httpx.MockTransport(handler)), data_mode="live")
    assert provider.quotes(["SPY"])
    assert provider.quotes(["QQQ"])
    assert provider.quotes(["IWM"]) == []
    budget = provider.budget_status()
    assert requests == 2
    assert budget["safety_limit"] == 2 and budget["remaining"] == 0 and budget["paused"] is True


def test_tradier_401_is_distinguishable_and_does_not_leak_credentials(caplog):
    token = "super-secret-token"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, request=request, text="sensitive upstream body")

    provider = TradierMarketDataProvider(token, "https://example.test/v1",
        httpx.Client(transport=httpx.MockTransport(handler)), data_mode="live")
    with caplog.at_level(logging.WARNING):
        assert provider.quotes(["SPY"]) == []
    status = provider.status()
    combined = f"{status.message}\n{caplog.text}"
    assert status.status == "degraded"
    assert status.message == "Tradier data unavailable: HTTP 401."
    assert token not in combined and "Authorization" not in combined
    assert "sensitive upstream body" not in combined
    assert "endpoint=/markets/quotes status=401" in caplog.text


def test_tradier_429_captures_rate_limit_headers(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, request=request, headers={
            "X-Ratelimit-Allowed": "120", "X-Ratelimit-Used": "120",
            "X-Ratelimit-Available": "0", "X-Ratelimit-Expiry": "1787752800",
        })

    provider = TradierMarketDataProvider("secret", "https://example.test/v1",
        httpx.Client(transport=httpx.MockTransport(handler)), data_mode="live")
    with caplog.at_level(logging.WARNING):
        assert provider.quotes(["SPY"]) == []
    status = provider.status()
    budget = provider.budget_status()
    assert status.status == "rate_limited"
    assert status.message == "Tradier data unavailable: HTTP 429."
    assert budget["provider_allowed"] == 120
    assert budget["provider_used"] == 120
    assert budget["provider_available"] == 0
    assert budget["paused"] is True


def test_tradier_timeout_reports_safe_request_error(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret network detail", request=request)

    provider = TradierMarketDataProvider("secret", "https://example.test/v1",
        httpx.Client(transport=httpx.MockTransport(handler)), data_mode="live")
    with caplog.at_level(logging.WARNING):
        assert provider.quotes(["SPY"]) == []
    assert provider.status().message == "Tradier data unavailable: ReadTimeout."
    assert "secret network detail" not in caplog.text


def test_tradier_invalid_json_and_shape_are_reported_safely():
    responses = [
        lambda request: httpx.Response(200, request=request, content=b"not-json"),
        lambda request: httpx.Response(200, request=request, json={"unexpected": {}}),
    ]
    for handler in responses:
        provider = TradierMarketDataProvider("secret", "https://example.test/v1",
            httpx.Client(transport=httpx.MockTransport(handler)), data_mode="live")
        assert provider.quotes(["SPY"]) == []
        assert provider.status().message == "Tradier returned an invalid response."


def test_unknown_tradier_mode_is_degraded_and_clearly_non_actionable(caplog):
    unused_client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, request=request, json={})))
    with caplog.at_level(logging.WARNING):
        provider = TradierMarketDataProvider(
            "secret", "https://example.test/v1", unused_client, data_mode="unknown"
        )
    status = provider.status()
    assert status.mode == "unknown" and status.status == "degraded"
    assert "TRADIER_DATA_MODE" in status.message
    assert "cannot be actionable" in status.message
    assert "Candidates remain non-actionable" in caplog.text
