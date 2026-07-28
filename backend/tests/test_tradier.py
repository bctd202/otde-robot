from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

from app.core.config import Settings, get_settings
from app.market_data.factory import get_provider
from app.market_data.mock import MockMarketDataProvider
from app.market_data.tradier import TradierMarketDataProvider

NY = ZoneInfo("America/New_York")
TODAY = datetime.now(NY).date()


def provider_for(handler) -> TradierMarketDataProvider:
    settings = Settings(
        tradier_access_token="test-token",
        tradier_base_url="https://api.tradier.test/v1",
    )
    client = httpx.Client(base_url=settings.tradier_base_url, transport=httpx.MockTransport(handler))
    return TradierMarketDataProvider(settings=settings, client=client)


def option(symbol: str, *, greeks=True, bid=0.40, ask=0.45):
    row = {
        "symbol": symbol, "expiration_date": TODAY.isoformat(), "strike": 551,
        "option_type": "call", "bid": bid, "ask": ask, "last": 0.42,
        "volume": 500, "open_interest": 900, "trade_date": 1_800_000_000_000,
    }
    if greeks:
        row["greeks"] = {"delta": 0.20, "gamma": 0.04, "theta": -0.08, "vega": 0.02, "mid_iv": 0.24}
    return row


def test_authentication_header_and_quote_normalization():
    def handler(request: httpx.Request):
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.headers["Accept"] == "application/json"
        assert request.url.path == "/v1/markets/quotes"
        return httpx.Response(200, json={"quotes": {"quote": {"symbol": "SPY", "last": 551.25, "trade_date": 1_800_000_000_000}}})

    quotes = provider_for(handler).quotes(["SPY"])
    assert quotes[0].symbol == "SPY"
    assert quotes[0].price == 551.25


def test_single_object_chain_normalization_and_same_day_selection():
    paths = []

    def handler(request: httpx.Request):
        paths.append(request.url.path)
        if request.url.path.endswith("/expirations"):
            return httpx.Response(200, json={"expirations": {"date": TODAY.isoformat()}})
        assert request.url.params["expiration"] == TODAY.isoformat()
        return httpx.Response(200, json={"options": {"option": option("SPY-CALL")}})

    chain = provider_for(handler).option_chain("SPY")
    assert len(chain) == 1
    assert chain[0].option_symbol == "SPY-CALL"
    assert paths[-1].endswith("/chains")


def test_list_chain_normalization():
    def handler(request: httpx.Request):
        if request.url.path.endswith("/expirations"):
            return httpx.Response(200, json={"expirations": {"date": [TODAY.isoformat()]}})
        return httpx.Response(200, json={"options": {"option": [option("SPY-C1"), option("SPY-C2")]}})

    assert [item.option_symbol for item in provider_for(handler).option_chain("SPY")] == ["SPY-C1", "SPY-C2"]


def test_missing_greeks_remain_none():
    def handler(request: httpx.Request):
        if request.url.path.endswith("/expirations"):
            return httpx.Response(200, json={"expirations": {"date": TODAY.isoformat()}})
        return httpx.Response(200, json={"options": {"option": option("SPY-NO-GREEKS", greeks=False)}})

    contract = provider_for(handler).option_chain("SPY")[0]
    assert contract.delta is contract.gamma is contract.theta is contract.vega is contract.iv is None


def test_missing_option_quote_fields_remain_none():
    missing = option("SPY-MISSING", greeks=False)
    for field in ("bid", "ask", "last", "volume", "open_interest"):
        missing.pop(field)

    def handler(request: httpx.Request):
        if request.url.path.endswith("/expirations"):
            return httpx.Response(200, json={"expirations": {"date": TODAY.isoformat()}})
        return httpx.Response(200, json={"options": {"option": missing}})

    contract = provider_for(handler).option_chain("SPY")[0]
    assert contract.bid is contract.ask is contract.last is None
    assert contract.volume is contract.open_interest is None


def test_no_same_day_expiration_does_not_request_chain():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"expirations": {"date": date(2030, 1, 1).isoformat()}})

    provider = provider_for(handler)
    assert provider.option_chain("AAPL") == []
    assert provider.unavailable_reason("AAPL") == "no same-day expiration"
    assert all(not path.endswith("/chains") for path in calls)


def test_live_failure_never_returns_mock_data():
    provider = provider_for(lambda _: httpx.Response(503, json={"error": "unavailable"}))
    assert provider.quotes(["SPY"]) == []
    assert provider.status().provider == "tradier"
    assert provider.status().status == "unavailable"


def test_factory_selects_provider_without_live_to_mock_fallback():
    settings = get_settings()
    original = settings.market_data_provider
    try:
        settings.market_data_provider = "mock"
        assert isinstance(get_provider(), MockMarketDataProvider)
        settings.market_data_provider = "tradier"
        assert isinstance(get_provider(), TradierMarketDataProvider)
        settings.market_data_provider = "unknown"
        try:
            get_provider()
        except ValueError as exc:
            assert "Unsupported MARKET_DATA_PROVIDER" in str(exc)
        else:
            raise AssertionError("Unknown provider should fail closed")
    finally:
        settings.market_data_provider = original
