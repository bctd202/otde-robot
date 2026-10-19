from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db.models import LotteryTracker
from app.services.lottery_tracker import track_lottery_scan
from app.services.parlay import rank_parlays
from app.services.session_candles import session_candles
from app.services.structured_intraday import evaluate_structured_setup
from test_lottery_tracker import LiveLotteryProvider
from test_performance import database

NY = ZoneInfo("America/New_York")


def test_session_filter_deduplicates_sorts_and_excludes_old_future_and_extended_bars():
    rows = LiveLotteryProvider().candles("SPY")
    boundary = rows[-1].timestamp
    extra = [rows[0].model_copy(update={"timestamp": rows[0].timestamp-timedelta(days=1)}),
             rows[0].model_copy(update={"timestamp": rows[0].timestamp-timedelta(minutes=1)}),
             rows[-1].model_copy(update={"timestamp": boundary+timedelta(minutes=1)})]
    assert session_candles(list(reversed(rows))+extra+[rows[0]], boundary) == rows


def test_main_signal_requires_eight_current_day_candles_and_records_inputs():
    market = LiveLotteryProvider()
    previous = [c.model_copy(update={"timestamp": c.timestamp-timedelta(days=1), "close": 900})
                for c in market.candles("SPY")]
    today = market.candles("SPY")
    market.now = today[0].timestamp+timedelta(minutes=1)
    market.candles = lambda *_: previous+today[:1]
    candidate = rank_parlays(market, ["SPY"], completed_at=today[0].timestamp)[0]
    assert candidate.signal_status == "UNAVAILABLE"
    assert candidate.input_evidence["candle_count"] == 1
    assert candidate.strategy_version == "parlay-v1-session-v2"
    market.now = today[-1].timestamp+timedelta(minutes=1)
    market.candles = lambda *_: previous+today
    mixed = rank_parlays(market, ["SPY"], completed_at=today[-1].timestamp)[0]
    market.candles = lambda *_: today
    clean = rank_parlays(market, ["SPY"], completed_at=today[-1].timestamp)[0]
    assert mixed == clean
    assert clean.input_evidence["first_candle_at"].endswith("13:30:00+00:00")
    assert clean.input_evidence["session_date"] == "2026-09-02"
    assert clean.input_evidence["opening_range"] and clean.input_evidence["vwap"]


def test_structured_cannot_use_prior_day_to_satisfy_first_hour():
    from test_structured_intraday import structured_candles
    previous = structured_candles()
    current = [c.model_copy(update={"timestamp": c.timestamp+timedelta(days=1)}) for c in previous[:1]]
    result = evaluate_structured_setup(previous+current, current[0].close, current[0].timestamp)
    assert result.status == "PASS"
    assert "full hour" in result.rejection_reasons[0]


def test_lotto_does_not_log_prior_session_context_at_open():
    market = LiveLotteryProvider()
    today = market.candles("SPY")
    previous = [c.model_copy(update={"timestamp": c.timestamp-timedelta(days=1)}) for c in today]
    market.now = datetime(2026, 9, 2, 9, 30, tzinfo=NY)
    market.candles = lambda *_: previous+today[:1]
    with database()() as db:
        track_lottery_scan(db, market, ["SPY"], market.now-timedelta(minutes=1), now=market.now)
        assert db.scalar(select(LotteryTracker)) is None
        market.now += timedelta(minutes=1)
        track_lottery_scan(db, market, ["SPY"], market.now-timedelta(minutes=1), now=market.now)
        assert db.scalar(select(LotteryTracker)) is None
