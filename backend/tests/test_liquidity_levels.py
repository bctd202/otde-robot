from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.market import LiquidityLevelsOut
from app.services.indicators import equal_levels


NY = ZoneInfo("America/New_York")
client = TestClient(app)


def level(price: float, minute: int) -> tuple[datetime, float]:
    return datetime(2026, 7, 17, 10, minute, tzinfo=NY), price


def test_no_equal_levels() -> None:
    assert equal_levels([]) == []
    assert equal_levels([level(550.0, 0), level(551.0, 1)]) == []


def test_one_equal_high_level() -> None:
    assert equal_levels([level(550.0, 0), level(550.04, 1)]) == [550.02]


def test_multiple_equal_high_levels() -> None:
    highs = [level(550.0, 0), level(550.04, 1), level(552.0, 2), level(552.02, 3)]
    assert equal_levels(highs) == [550.02, 552.01]


def test_one_equal_low_level() -> None:
    assert equal_levels([level(545.0, 0), level(545.02, 1)]) == [545.01]


def test_multiple_equal_low_levels() -> None:
    lows = [level(545.0, 0), level(545.02, 1), level(543.0, 2), level(543.04, 3)]
    assert equal_levels(lows) == [543.02, 545.01]


def test_liquidity_level_defaults_are_independent() -> None:
    values = dict(previous_day_high=551, previous_day_low=545, opening_range_high=550,
                  opening_range_low=548, session_high=552, session_low=547, vwap=549)
    first = LiquidityLevelsOut(**values)
    second = LiquidityLevelsOut(**values)
    first.equal_highs.append(550.5)
    assert second.equal_highs == []
    assert first.equal_lows == second.equal_lows == []


def test_dashboard_validates_level_arrays_for_every_symbol() -> None:
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload["levels"]) == {"SPY", "QQQ", "IWM"}
    for symbol in ("SPY", "QQQ", "IWM"):
        assert isinstance(payload["levels"][symbol]["equal_highs"], list)
        assert isinstance(payload["levels"][symbol]["equal_lows"], list)


def test_dashboard_integration_returns_200_with_mock_data() -> None:
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    assert response.json()["provider_status"]["mode"] == "mock"
