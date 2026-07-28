from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.main import app
from app.market_data.mock import MockMarketDataProvider
from app.schemas.market import OptionContractOut
from app.services.parlay import clamp_parlay_score, contract_rejections, rank_parlays

NY = ZoneInfo("America/New_York")
client = TestClient(app)


def contract(*, bid=0.40, ask=0.45, volume=500) -> OptionContractOut:
    return OptionContractOut(
        symbol="SPY", option_symbol="SPY-TEST", expiration=date.today(), strike=551,
        right="call", bid=bid, ask=ask, last=0.42, volume=volume, open_interest=None,
        timestamp=datetime.now(NY),
    )


def test_contract_price_filtering():
    assert "no contract within price range" in contract_rejections(contract(ask=1.20), 551, date.today())
    assert "no contract within price range" in contract_rejections(contract(ask=0.10), 551, date.today())
    assert "no contract within price range" not in contract_rejections(contract(), 551, date.today())
    assert contract_rejections(contract(), 551, date.today()) == []  # missing open interest is allowed


def test_spread_filtering():
    assert "spread too wide" in contract_rejections(contract(bid=0.30, ask=0.50), 551, date.today())
    assert "spread too wide" not in contract_rejections(contract(bid=0.40, ask=0.45), 551, date.today())


def test_ranking_and_optional_open_interest():
    results = rank_parlays(MockMarketDataProvider(), ["SPY", "QQQ", "IWM"], enforce_market_hours=False)
    assert [item.rank for item in results] == [1, 2, 3]
    assert results == sorted(results, key=lambda item: (item.setup_score, item.volume or 0), reverse=True)
    assert any(item.contract_symbol for item in results)
    assert all(0 <= item.setup_score <= 100 for item in results)


def test_score_clamping():
    assert clamp_parlay_score(-10) == 0
    assert clamp_parlay_score(50.6) == 51
    assert clamp_parlay_score(150) == 100


def test_parlays_endpoint_returns_ranked_universe():
    response = client.get("/api/parlays")
    assert response.status_code == 200
    payload = response.json()
    assert payload["paper_only"] is True
    assert len(payload["candidates"]) == 12
    assert [item["rank"] for item in payload["candidates"]] == list(range(1, 13))
