from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import router
from app.db.models import LotteryQuoteSnapshot, LotteryTracker
from app.db.session import Base, get_db
from app.schemas.market import CandleOut, OptionContractOut, ProviderStatus, Quote
from app.services.lottery_tracker import (close_lottery_trackers, serialize_tracker,
                                          track_lottery_scan, tracker_points)

NY = ZoneInfo("America/New_York")
NOW = datetime(2026, 9, 2, 10, 5, tzinfo=NY)


class LiveLotteryProvider:
    def __init__(self) -> None:
        self.now = NOW
        self.bid = .18
        self.ask = .20

    def status(self) -> ProviderStatus:
        return ProviderStatus(provider="tradier", mode="live", status="healthy", delay_seconds=0,
                              latest_timestamp=self.now, message="test")

    def candles(self, symbol: str, timeframe: str = "1m") -> list[CandleOut]:
        start = datetime.combine(self.now.date(), time(9, 30), tzinfo=NY)
        count = int((self.now - start).total_seconds() // 60)
        rows = []
        for index in range(count):
            close = 100 + index * .03
            rows.append(CandleOut(symbol=symbol, timeframe=timeframe,
                timestamp=start + timedelta(minutes=index), open=close - .02,
                high=close + .04, low=close - .04, close=close, volume=200_000 + index * 1_000))
        return rows

    def quotes(self, symbols: list[str]) -> list[Quote]:
        price = self.candles("SPY")[-1].close
        return [Quote(symbol=symbol, price=price, timestamp=self.now) for symbol in symbols]

    def option_chain(self, symbol: str, expiration=None) -> list[OptionContractOut]:
        selected = expiration or self.now.date()
        strike = 102.0
        option_symbol = f"{symbol}{selected:%y%m%d}C{int(strike * 1000):08d}"
        return [OptionContractOut(symbol=symbol, option_symbol=option_symbol,
            expiration=selected, strike=strike, right="call", bid=self.bid, ask=self.ask,
            last=round((self.bid + self.ask) / 2, 2), volume=1_500, open_interest=3_000,
            iv=.35, delta=.15, gamma=.05, theta=-.08, vega=.02, timestamp=self.now,
            bid_timestamp=self.now, ask_timestamp=self.now, provider="tradier", data_mode="live")]


def test_tracker_records_each_scan_and_keeps_marking_after_contract_stops_qualifying():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    provider = LiveLotteryProvider()
    with Session(engine) as db:
        track_lottery_scan(db, provider, ["SPY"], provider.now - timedelta(minutes=1))
        db.commit()
        tracker = db.scalar(select(LotteryTracker))
        assert tracker is not None
        assert tracker.entry_ask == .20
        assert tracker.entry_bid == .18
        assert len(tracker_points(db, tracker.id)) == 1
        assert tracker_points(db, tracker.id)[0].is_qualified is True

        provider.now += timedelta(minutes=1)
        provider.bid = .45
        provider.ask = .48  # Above the lotto filter, but the exact contract must keep tracking.
        track_lottery_scan(db, provider, ["SPY"], provider.now - timedelta(minutes=1))
        db.commit()

        points = tracker_points(db, tracker.id)
        summary = serialize_tracker(tracker, points)
        assert len(points) == 2
        assert points[-1].is_qualified is False
        assert summary["peak_multiple"] == 2.25
        assert summary["peak_sellable_value"] == 45
        assert summary["hit_2x_at"].replace(tzinfo=ZoneInfo("UTC")) == provider.now.astimezone(ZoneInfo("UTC"))
        assert summary["currently_qualified"] is False


def test_same_completed_candle_cannot_duplicate_a_chart_point():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    provider = LiveLotteryProvider()
    evaluation_at = provider.now - timedelta(minutes=1)
    with Session(engine) as db:
        track_lottery_scan(db, provider, ["SPY"], evaluation_at)
        db.commit()
        track_lottery_scan(db, provider, ["SPY"], evaluation_at)
        db.commit()
        assert len(db.scalars(select(LotteryQuoteSnapshot)).all()) == 1


def test_trackers_close_after_the_regular_session_without_fabricating_a_close_quote():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    provider = LiveLotteryProvider()
    with Session(engine) as db:
        track_lottery_scan(db, provider, ["SPY"], provider.now - timedelta(minutes=1))
        db.commit()
        tracker = db.scalar(select(LotteryTracker))
        assert tracker is not None and tracker.status == "ACTIVE"
        last_quote = tracker.last_quote_at

        close_time = datetime.combine(provider.now.date(), time(16, 0, 5), tzinfo=NY)
        assert close_lottery_trackers(db, close_time) == 1
        db.commit()
        assert tracker.status == "CLOSED"
        assert tracker.closed_at is not None
        assert tracker.last_quote_at == last_quote


def test_tracker_api_exposes_the_summary_and_scan_points():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    provider = LiveLotteryProvider()
    with Session(engine) as db:
        trackers = track_lottery_scan(db, provider, ["SPY"], provider.now - timedelta(minutes=1))
        db.commit()
        tracker_id = trackers[0].id

    application = FastAPI()
    application.include_router(router, prefix="/api")

    def override_db():
        with Session(engine) as db:
            yield db

    application.dependency_overrides[get_db] = override_db
    client = TestClient(application)
    listing = client.get("/api/lottery-trackers?trading_date=2026-09-02")
    assert listing.status_code == 200
    assert listing.json()["trackers"][0]["entry_cost"] == 20
    assert listing.json()["performance_basis"] == "Subsequent sellable bid"

    detail = client.get(f"/api/lottery-trackers/{tracker_id}")
    assert detail.status_code == 200
    assert detail.json()["tracker"]["point_count"] == 1
    assert detail.json()["points"][0]["bid_value"] == 18
    assert detail.json()["paper_only"] is True
