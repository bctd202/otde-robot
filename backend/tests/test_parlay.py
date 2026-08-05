from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.market_data.mock import MockMarketDataProvider
from app.schemas.market import ProviderStatus
from app.services.parlay import _score_label, rank_parlays

NY = ZoneInfo("America/New_York")
FIXED_SESSION_TIME = datetime(2026, 1, 15, 10, 5, tzinfo=NY)


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED_SESSION_TIME if tz is None else FIXED_SESSION_TIME.astimezone(tz)


@pytest.fixture(autouse=True)
def fixed_eastern_strategy_clock(monkeypatch):
    monkeypatch.setattr("app.services.parlay.datetime", FixedDateTime)


def mock_provider():
    return MockMarketDataProvider(now=FIXED_SESSION_TIME)


def board():
    settings = get_settings()
    return rank_parlays(mock_provider(), settings.parlay_symbol_list)


def test_default_mock_board_has_complete_deterministic_variety():
    first, second = board(), board()
    assert [item.model_dump() for item in first] == [item.model_dump() for item in second]
    assert len(first) == 12
    assert {item.symbol for item in first} == set(get_settings().parlay_symbol_list)
    statuses = [item.signal_status for item in first]
    assert statuses == ["PASS"] * 12
    assert {item.direction for item in first} >= {"call", "put"}
    provider = mock_provider()
    for symbol in get_settings().parlay_symbol_list:
        assert provider.quotes([symbol])
        assert provider.candles(symbol, "1m")
        chain = provider.option_chain(symbol)
        assert {contract.right for contract in chain} == {"call", "put"}
        assert all(contract.volume and contract.open_interest for contract in chain)


def test_plans_score_labels_actions_and_sorting():
    results = board()
    order = {"BUY": 0, "WATCH": 1, "MISSED": 2, "PASS": 3, "UNAVAILABLE": 4}
    assert [item.ranking_position for item in results] == list(range(1, 13))
    assert [(order[item.signal_status], -item.score) for item in results] == sorted(
        (order[item.signal_status], -item.score) for item in results
    )
    assert [_score_label(score) for score in (85, 70, 55, 54)] == [
        "PLAY", "WATCH CLOSELY", "DEVELOPING", "PASS"
    ]
    directional = next(item for item in results if item.direction != "none")
    assert directional.primary_action == "No verified contract available"
    assert directional.underlying_trigger is not None and directional.contract is None
    for passed in (item for item in results if item.signal_status == "PASS"):
        assert passed.entry_low is None and passed.first_option_target is None
        assert passed.contract is None


class UnavailableProvider:
    def status(self):
        return ProviderStatus(provider="tradier", mode="live", status="unavailable", delay_seconds=0,
            latest_timestamp=datetime.now(NY), message="Tradier data unavailable")

    def quotes(self, symbols):
        return []


def test_unavailable_fails_closed_without_mock_fallback():
    results = rank_parlays(UnavailableProvider(), ["SPY", "QQQ"])
    assert len(results) == 2
    assert all(item.signal_status == "UNAVAILABLE" for item in results)
    assert all(item.contract is None and item.entry_low is None for item in results)
    assert all(item.primary_action == "UNAVAILABLE — PROVIDER UNAVAILABLE" for item in results)


class EmptyChainProvider(MockMarketDataProvider):
    def option_chain(self, symbol):
        return []


class FailedChainProvider(EmptyChainProvider):
    failed = False

    def option_chain(self, symbol):
        self.failed = True
        return []

    def status(self):
        status = super().status()
        if self.failed:
            status.status = "unavailable"
        return status


class PremiumMissProvider(MockMarketDataProvider):
    def option_chain(self, symbol):
        chain = super().option_chain(symbol)
        for contract in chain:
            if contract.right == "call":
                contract.bid = .68
                contract.ask = .80
                contract.last = .40
        return chain


def test_empty_and_failed_option_chains_have_accurate_reasons():
    healthy = rank_parlays(EmptyChainProvider(now=FIXED_SESSION_TIME), ["SPY"])[0]
    failed = rank_parlays(FailedChainProvider(now=FIXED_SESSION_TIME), ["SPY"])[0]
    assert healthy.contract_verification_reason == "No same-day expiration"
    assert failed.contract_verification_reason == "Option chain unavailable"
    assert healthy.signal_status == failed.signal_status == "PASS"


def test_missed_premium_action_reports_the_actual_cause():
    missed = rank_parlays(PremiumMissProvider(now=FIXED_SESSION_TIME), ["AAPL"])[0]
    assert missed.signal_status == "PASS"
    assert missed.contract is None
    assert missed.primary_action == "No verified contract available"


class PartialQuoteProvider(MockMarketDataProvider):
    def quotes(self, symbols):
        if symbols == ["BROKEN"]:
            raise ValueError("Malformed or unsupported symbol")
        return super().quotes(symbols)


def test_one_bad_quote_does_not_block_other_symbols():
    results = rank_parlays(PartialQuoteProvider(now=FIXED_SESSION_TIME), ["BROKEN", "SPY"])
    by_symbol = {item.symbol: item for item in results}

    assert by_symbol["BROKEN"].unavailable_reason == "Quote unavailable"
    assert by_symbol["SPY"].unavailable_reason is None


def test_parlay_endpoint_returns_ranked_paper_board(monkeypatch):
    monkeypatch.setattr("app.api.routes.get_provider", mock_provider)
    response = TestClient(app).get("/api/parlays")
    assert response.status_code == 200
    body = response.json()
    assert body["provider_status"]["mode"] == "mock"
    assert body["paper_only"] is True
    assert body["universe"] == get_settings().parlay_symbol_list
    assert len(body["candidates"]) == 12
    assert body["scanner_health"] == {
        "candidate_count": 12,
        "unavailable_candidate_count": 0,
        "provider_status": "healthy",
    }


def test_live_and_replay_share_identical_completed_candle_evaluation():
    from app.services.backtest import replay_evaluation
    from app.services.parlay import evaluate_underlying_setup
    provider=mock_provider();candles=provider.candles("SPY","1m")
    live=evaluate_underlying_setup(candles,candles[-1].close)
    replay=replay_evaluation(candles,candles[-1].close)
    assert replay == live
    assert (replay.direction,replay.trigger,replay.stop,replay.target,replay.checks,replay.confirmed) == (live.direction,live.trigger,live.stop,live.target,live.checks,live.confirmed)
