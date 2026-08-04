from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import routes
from app.db.models import ParlayPaperPosition
from app.db.session import Base, get_db
from app.main import app
from app.schemas.market import OptionContractOut, ProviderStatus, Quote
from app.services import paper_positions as paper_position_service


NOW = datetime(2026, 7, 29, 14, 30, tzinfo=timezone.utc)


class Provider:
    def __init__(self, underlying: float = 101, bid: float = 0.7, available: bool = True):
        self.underlying, self.bid, self.available = underlying, bid, available
        self.option_chain_calls = 0

    def status(self):
        return ProviderStatus(provider="tradier", mode="live", status="healthy" if self.available else "unavailable",
                              delay_seconds=0, latest_timestamp=NOW, message="paper test data")

    def quotes(self, symbols):
        return [Quote(symbol=symbols[0], price=self.underlying, timestamp=NOW)] if self.available else []

    def option_chain(self, symbol):
        self.option_chain_calls += 1
        if not self.available:
            return []
        return [OptionContractOut(symbol=symbol, option_symbol=f"SPY260729{kind}00101000", expiration=date(2026, 7, 29),
                                  strike=101, right=right, bid=self.bid, ask=self.bid + .05, last=self.bid,
                                  volume=500, open_interest=900, timestamp=NOW, bid_timestamp=NOW,
                                  ask_timestamp=NOW, provider="tradier", data_mode="live")
                for kind, right in (("C", "call"), ("P", "put"))]


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    local = sessionmaker(bind=engine, expire_on_commit=False)
    provider = Provider()

    def db_override():
        with local() as session:
            yield session

    app.dependency_overrides[get_db] = db_override
    monkeypatch.setattr(routes, "get_provider", lambda: provider)
    monkeypatch.setattr(paper_position_service, "eastern_trading_date", lambda: date(2026, 7, 29))
    with TestClient(app) as test_client:
        yield test_client, local, provider
    app.dependency_overrides.clear()


def payload(status="BUY", direction="call"):
    return {"symbol": "SPY", "option_symbol": "SPY260729C00101000", "direction": direction,
            "expiration": "2026-07-29", "strike": 101, "quantity": 1, "option_ask": .75,
            "underlying_entry_price": 101, "underlying_trigger": 100,
            "underlying_invalidation": 99 if direction == "call" else 103,
            "first_underlying_target": 102 if direction == "call" else 100,
            "stretch_underlying_target": 104 if direction == "call" else 98,
            "first_option_target": 1.5, "stretch_option_target": 3, "score": 91,
            "score_label": "PLAY", "reasons": ["VWAP reclaimed"], "signal_status": status,
            "provider_mode": "live", "entry_timestamp": NOW.isoformat(), "paper_only": True}


def test_create_buy_uses_exact_ask_and_is_paper_only(client):
    response = client[0].post("/api/paper-positions", json=payload())
    assert response.status_code == 201
    body = response.json()
    assert body["entry_option_price"] == .75
    assert body["total_debit"] == 75
    assert body["quantity"] == 1 and body["paper_only"] is True
    assert body["entry_reasons"] == ["VWAP reclaimed"]


@pytest.mark.parametrize("status", ["WATCH", "MISSED", "PASS", "UNAVAILABLE"])
def test_rejects_non_buy_entries(client, status):
    response = client[0].post("/api/paper-positions", json=payload(status))
    assert response.status_code == 422


def test_duplicate_active_position_is_rejected(client):
    assert client[0].post("/api/paper-positions", json=payload()).status_code == 201
    assert client[0].post("/api/paper-positions", json=payload()).status_code == 409


@pytest.mark.parametrize(("underlying", "bid", "expected"), [
    (101, .70, "HOLD"), (102, .70, "TAKE_PROFIT"), (98, .70, "EXIT"), (101, 3, "EXIT")])
def test_call_management_states(client, underlying, bid, expected):
    client[0].post("/api/paper-positions", json=payload())
    client[2].underlying, client[2].bid = underlying, bid
    body = client[0].get("/api/paper-positions").json()["positions"][0]
    assert body["decision_status"] == expected


def test_put_invalidation_is_direction_aware(client):
    put = payload(direction="put")
    put["option_symbol"] = "SPY260729P00101000"
    response = client[0].post("/api/paper-positions", json=put)
    assert response.status_code == 201
    position_id = response.json()["id"]
    with client[1]() as db:
        row = db.get(ParlayPaperPosition, position_id)
        assert row is not None
        assert routes.serialize(row, option_price=.7, underlying_price=104).decision_status == "EXIT"


def test_missing_market_data_preserves_active_position(client):
    created = client[0].post("/api/paper-positions", json=payload()).json()
    client[2].available = False
    body = client[0].get("/api/paper-positions").json()["positions"][0]
    assert body["id"] == created["id"] and body["lifecycle_status"] == "ACTIVE"
    assert body["decision_status"] == "DATA_UNAVAILABLE"
    assert body["next_action"] == "DATA UNAVAILABLE — RETAINING LAST KNOWN POSITION STATE"
    assert body["current_option_price"] == .75
    assert body["current_underlying_price"] == 101
    assert body["last_marked_at"] == created["last_marked_at"]
    assert body["unrealized_pnl"] == 0
    assert body["pnl_percent"] == 0
    assert body["data_freshness"] == "data_unavailable"
    assert body["closed_at"] is None and body["exit_option_price"] is None


def test_unavailable_provider_cannot_exit_at_stale_mark(client):
    created = client[0].post("/api/paper-positions", json=payload()).json()
    client[2].available = False
    response = client[0].post(f"/api/paper-positions/{created['id']}/exit",
                              json={"reason": "MANUAL PAPER EXIT", "paper_only": True})
    assert response.status_code == 409
    assert response.json()["detail"] == "No current defensible paper exit price is available"
    with client[1]() as db:
        position = db.get(ParlayPaperPosition, created["id"])
        assert position is not None
        assert position.lifecycle_status == "ACTIVE"
        assert position.exit_option_price is None
        assert position.closed_at is None


def test_explicit_exit_realized_pnl_and_repeated_exit_rejection(client):
    created = client[0].post("/api/paper-positions", json=payload()).json()
    client[2].bid = 1.25
    response = client[0].post(f"/api/paper-positions/{created['id']}/exit",
                              json={"reason": "MANUAL PAPER EXIT", "paper_only": True})
    assert response.status_code == 200
    assert response.json()["lifecycle_status"] == "CLOSED"
    assert response.json()["realized_pnl"] == 50
    assert response.json()["exit_reason"] == "MANUAL PAPER EXIT"
    assert client[0].post(f"/api/paper-positions/{created['id']}/exit",
                          json={"reason": "again", "paper_only": True}).status_code == 409


def test_past_expiration_becomes_expired_without_market_mark_or_settlement(client, monkeypatch):
    created = client[0].post("/api/paper-positions", json=payload()).json()
    calls_before = client[2].option_chain_calls
    monkeypatch.setattr(paper_position_service, "eastern_trading_date", lambda: date(2026, 7, 30))

    body = client[0].get("/api/paper-positions").json()["positions"][0]

    assert body["id"] == created["id"]
    assert body["lifecycle_status"] == "EXPIRED"
    assert body["decision_status"] == "EXPIRED"
    assert body["data_freshness"] == "historical_stale"
    assert body["current_option_price"] == .75
    assert body["current_underlying_price"] == 101
    assert body["unrealized_pnl"] is None and body["pnl_percent"] is None
    assert body["expired_at"] is not None
    assert body["closed_at"] is None and body["exit_option_price"] is None
    assert client[2].option_chain_calls == calls_before


def test_expired_position_cannot_be_manually_exited(client, monkeypatch):
    created = client[0].post("/api/paper-positions", json=payload()).json()
    monkeypatch.setattr(paper_position_service, "eastern_trading_date", lambda: date(2026, 7, 30))
    response = client[0].post(f"/api/paper-positions/{created['id']}/exit",
                              json={"reason": "MANUAL PAPER EXIT", "paper_only": True})
    assert response.status_code == 409
    assert response.json()["detail"] == "Expired paper positions cannot be exited"
