from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import SignalPerformance
from app.db.session import Base
from app.market_data.mock import MockMarketDataProvider
from app.schemas.market import OptionContractOut, ProviderStatus, Quote
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


def test_unknown_and_delayed_data_modes_are_explicitly_non_actionable():
    unknown = validate_contract(contract(data_mode="unknown"), "IWN", now=NOW)
    delayed = validate_contract(contract(data_mode="delayed"), "IWN", now=NOW)
    assert unknown.authentic and not unknown.actionable
    assert "TRADIER_DATA_MODE" in unknown.reason and "not actionable" in unknown.reason
    assert delayed.authentic and not delayed.actionable
    assert delayed.reason == "Delayed Tradier data is research-only and not actionable"


def test_strategy_specific_dte_window_preserves_authenticity_and_controls_actionability():
    future = contract(option_symbol="IWN260812C00250000", expiration=date(2026, 8, 12))
    same_day_policy = validate_contract(future, "IWN", now=NOW)
    structured_policy = validate_contract(future, "IWN", now=NOW, min_dte=5, max_dte=14)
    assert same_day_policy.authentic and not same_day_policy.actionable
    assert "same-day" in same_day_policy.reason
    assert structured_policy.authentic and structured_policy.actionable


class IwnTradierMissingExpiration:
    def __init__(self):
        self.now = NOW
        base = MockMarketDataProvider(now=NOW)
        self._candles = base.candles("SPY")
        for candle in self._candles:
            candle.symbol = "IWN"
            candle.open -= 300
            candle.high -= 300
            candle.low -= 300
            candle.close -= 300

    def status(self):
        return ProviderStatus(provider="tradier", mode="live", status="healthy", delay_seconds=0,
                              latest_timestamp=NOW, message="Tradier live test fixture")

    def quotes(self, symbols):
        return [Quote(symbol="IWN", price=self._candles[-1].close, timestamp=NOW)]

    def candles(self, symbol, timeframe="1m"):
        return self._candles

    def expirations(self, symbol):
        return [date(2026, 8, 5)]

    def option_chain(self, symbol):
        if NOW.date() not in self.expirations(symbol):
            return []
        raise AssertionError("Fixture must not fabricate a chain for an unlisted expiration")


def test_iwn_tradier_missing_listed_expiration_keeps_underlying_without_live_contamination():
    candidate = rank_parlays(IwnTradierMissingExpiration(), ["IWN"])[0]
    assert candidate.direction == "call" and candidate.underlying_trigger is not None
    assert candidate.primary_action == "No verified contract available"
    assert candidate.contract_verification_reason == "Requested/current expiration is not listed by Tradier"
    assert candidate.contract is None and candidate.contract_cost is None and candidate.midpoint is None
    assert candidate.spread_percent is None and candidate.entry_low is None and not candidate.actionable
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        track_candidates(db, [candidate])
        assert db.scalars(select(SignalPerformance).where(SignalPerformance.source == "LIVE")).all() == []
