from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import SignalPerformance
from app.db.session import Base
from app.market_data.mock import MockMarketDataProvider
from app.schemas.market import OptionContractOut
from app.services.contracts import validate_contract
from app.services.parlay import rank_parlays
from app.services.performance import track_candidates

NOW = datetime(2026, 8, 4, 14, 0, tzinfo=timezone.utc)


def contract(**changes):
    values = dict(symbol="IWN", option_symbol="IWN260804C00250000", expiration=date(2026, 8, 4),
                  strike=250, right="call", bid=.40, ask=.45, last=.42, volume=500,
                  open_interest=900, timestamp=NOW, bid_timestamp=NOW, ask_timestamp=NOW,
                  provider="tradier", data_mode="live")
    values.update(changes)
    return OptionContractOut(**values)


def test_occ_identity_is_independently_compared_to_every_chain_field():
    assert validate_contract(contract(), "IWN", now=NOW).actionable
    for changed in (dict(symbol="IWM"), dict(expiration=date(2026, 8, 5)), dict(strike=251), dict(right="put")):
        result = validate_contract(contract(**changed), "IWN", now=NOW)
        assert not result.authentic and not result.actionable
        assert "disagrees" in result.reason


def test_authenticity_is_separate_from_quote_and_liquidity_eligibility():
    cases = [
        (dict(bid=0), "Invalid bid/ask"),
        (dict(ask=.35), "Invalid bid/ask"),
        (dict(bid_timestamp=NOW-timedelta(minutes=3)), "Stale bid/ask quote"),
        (dict(bid=.20, ask=.45), "Spread too wide"),
        (dict(volume=249), "Option volume too low"),
        (dict(open_interest=499), "Open interest too low"),
    ]
    for changes, reason in cases:
        result = validate_contract(contract(**changes), "IWN", now=NOW)
        assert result.authentic and not result.actionable and result.reason == reason


class MissingExpiration(MockMarketDataProvider):
    def option_chain(self, symbol):
        return []


def test_iwn_underlying_setup_survives_absent_tradier_expiration_without_live_contamination(monkeypatch):
    monkeypatch.setitem(__import__("app.market_data.mock", fromlist=["BASE"]).BASE, "IWN", 250.0)
    monkeypatch.setitem(__import__("app.market_data.mock", fromlist=["PROFILE"]).PROFILE, "IWN", "buy_call")
    candidate = rank_parlays(MissingExpiration(now=NOW), ["IWN"])[0]
    assert candidate.direction == "call" and candidate.underlying_trigger is not None
    assert candidate.primary_action == "No verified contract available"
    assert candidate.contract is None and candidate.contract_cost is None and not candidate.actionable
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        track_candidates(db, [candidate])
        assert db.scalars(select(SignalPerformance).where(SignalPerformance.source == "LIVE")).all() == []
