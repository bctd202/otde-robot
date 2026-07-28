from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.main import app
from app.market_data.mock import MockMarketDataProvider
from app.schemas.market import CandleOut, OptionContractOut, Quote
from app.services.parlay import rank_parlays

NY = ZoneInfo("America/New_York")


class StubProvider:
    def quotes(self, symbols):
        return [Quote(symbol=s, price=100, timestamp=datetime.now(NY)) for s in symbols]

    def candles(self, symbol, timeframe="1m"):
        now = datetime.now(NY)
        return [CandleOut(symbol=symbol, timeframe=timeframe, timestamp=now + timedelta(minutes=i),
            open=100 + i, high=101 + i, low=99 + i, close=100.5 + i, volume=1000) for i in range(3)]

    def option_chain(self, symbol):
        now = datetime.now(NY)
        return [OptionContractOut(symbol=symbol, option_symbol=f"{symbol}C", expiration=date.today(),
            strike=103, right="call", bid=.45, ask=.50, last=.48, volume=1200,
            open_interest=3000, timestamp=now)]


def test_parlay_filters_cost_and_ranks_deterministically():
    result = rank_parlays(StubProvider(), ["SPY"])[0]
    assert result.rank == "PLAY"
    assert result.contract_cost == 50
    assert result.unavailable_reason is None


def test_parlay_reports_unavailable_reason():
    provider = StubProvider()
    provider.option_chain = lambda symbol: []
    result = rank_parlays(provider, ["SPY"])[0]
    assert result.rank == "PASS"
    assert result.unavailable_reason == "Same-day option chain unavailable; candidate was not evaluated."


def test_parlay_endpoint_preserves_mock_mode(monkeypatch):
    monkeypatch.setattr("app.api.routes.get_provider", lambda: MockMarketDataProvider())
    response = TestClient(app).get("/api/parlays")
    assert response.status_code == 200
    body = response.json()
    assert body["provider_status"]["mode"] == "mock"
    assert body["paper_only"] is True
    assert len(body["universe"]) == 12
