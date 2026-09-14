from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import AutomatedOptionMark, SignalPerformance
from app.db.session import Base
from app.schemas.market import (CandleOut, OptionContractOut, ParlayCandidateOut,
                                ProviderStatus)
from app.services.performance import (analytics_exclusion_reason, deduplicate_positions,
                                      evaluate_open_signals, metrics,
                                      option_shadow_results, performance_chart_data, track_candidates,
                                      update_outcome)
from app.api.routes import _ledger, performance

def row(direction="CALL", signal_id="x", ticker="SPY"):
    now=datetime(2026,8,3,14,30,tzinfo=timezone.utc)
    return SignalPerformance(signal_id=signal_id,source="LIVE",dedupe_key=signal_id,ticker=ticker,direction=direction,backend_status="BUY",setup_type="directional-liquidity",strategy_mode="ONE_MIN_0DTE",strategy_version="v",strategy_snapshot={},condition_snapshot={},trading_date=date(2026,8,3),triggered_at=now,entry_price=100,stop_price=99,target_price=101.5,exit_reason="OPEN",mfe_r=0,mae_r=0,score=90,user_entered=False,conservative_same_candle=False,created_at=now,updated_at=now,last_evaluated_at=now)

def test_target_stop_and_same_candle_conservative_resolution():
    target=row();update_outcome(target,101.5,100.2,101.5,target.triggered_at+timedelta(minutes=5));assert target.exit_reason=="TARGET" and target.result_r==1.5
    stop=row();update_outcome(stop,100.2,99,99,stop.triggered_at+timedelta(minutes=5));assert stop.exit_reason=="STOP" and stop.result_r==-1
    both=row();update_outcome(both,102,98,99,both.triggered_at+timedelta(minutes=5));assert both.exit_reason=="STOP" and both.conservative_same_candle

def test_closed_paper_option_return_overrides_underlying_return():
    performance=row();performance.result_return_pct=.09
    paper=SimpleNamespace(lifecycle_status="CLOSED",entry_option_price=.23,exit_option_price=.61)
    payload=_ledger(performance,paper)
    assert payload["result_return_pct"]==165.2174
    assert payload["return_basis"]=="PAPER_OPTION"
    assert payload["paper_entry_option_price"]==.23 and payload["paper_exit_option_price"]==.61

def test_timed_exit_excursions_duration_and_open_metric_exclusion():
    closed=row();update_outcome(closed,100.8,99.6,100.2,closed.triggered_at+timedelta(minutes=15),cutoff=True)
    opened=row();opened.signal_id="open";opened.dedupe_key="open"
    summary=metrics([closed,opened])
    assert closed.result_r==0.2 and closed.mfe_r==0.8 and closed.mae_r==0.4 and closed.duration_minutes==15
    assert summary["open_signals"]==1 and summary["average_r"]==0.2 and summary["win_rate"]==100

class CandleProvider:
    def __init__(self, candles, latest, status="healthy"): self.rows,self.latest,self.provider_status=candles,latest,status
    def status(self): return ProviderStatus(provider="test",mode="mock",status=self.provider_status,delay_seconds=0,latest_timestamp=self.latest,message="test")
    def candles(self,ticker,timeframe="1m"):
        assert timeframe=="1m"
        return self.rows

def database():
    engine=create_engine("sqlite://",poolclass=StaticPool,connect_args={"check_same_thread":False});Base.metadata.create_all(engine)
    return sessionmaker(bind=engine,expire_on_commit=False)

def candle(stamp,high,low,close):
    return CandleOut(symbol="SPY",timeframe="1m",timestamp=stamp,open=100,high=high,low=low,close=close,volume=100)

def test_crossings_between_refreshes_are_processed_chronologically_and_once():
    local=database();start=datetime(2026,8,3,14,30,tzinfo=timezone.utc)
    first=candle(start+timedelta(minutes=1),101.5,100,101.2)
    later_stop=candle(start+timedelta(minutes=2),100,99,99)
    with local() as db:
        trade=row();db.add(trade);db.commit()
        evaluate_open_signals(db,CandleProvider([later_stop,first],start+timedelta(minutes=4)))
        assert trade.exit_reason=="TARGET" and trade.exit_at==first.timestamp
        cursor=trade.last_evaluated_at
        evaluate_open_signals(db,CandleProvider([first,later_stop],start+timedelta(minutes=5)))
        assert trade.exit_reason=="TARGET" and trade.last_evaluated_at==cursor

def test_stop_between_refreshes_and_restart_cursor_continuation():
    local=database();start=datetime(2026,8,3,14,30,tzinfo=timezone.utc)
    neutral=candle(start+timedelta(minutes=1),100.5,99.5,100.2)
    stop=candle(start+timedelta(minutes=2),100.2,98.8,99)
    with local() as db: db.add(row());db.commit();evaluate_open_signals(db,CandleProvider([neutral],start+timedelta(minutes=3)))
    with local() as restarted:
        trade=restarted.get(SignalPerformance,"x");assert trade.last_evaluated_at.replace(tzinfo=timezone.utc)==neutral.timestamp
        evaluate_open_signals(restarted,CandleProvider([neutral,stop],start+timedelta(minutes=4)))
        assert trade.exit_reason=="STOP" and trade.last_evaluated_at.replace(tzinfo=timezone.utc)==stop.timestamp

def test_session_cutoff_uses_completed_candle_close():
    local=database();start=datetime(2026,8,3,19,44,tzinfo=timezone.utc)
    cutoff=candle(start+timedelta(minutes=1),100.5,99.5,100.25)
    with local() as db:
        trade=row();trade.triggered_at=start;trade.last_evaluated_at=start;db.add(trade);db.commit()
        evaluate_open_signals(db,CandleProvider([cutoff],start+timedelta(minutes=3)))
        assert trade.exit_reason=="TIMED_EXIT" and trade.exit_price==100.25 and trade.result_r==.25


def test_later_session_candles_quarantine_an_open_signal_instead_of_scoring_it():
    local=database();start=datetime(2026,8,3,14,30,tzinfo=timezone.utc)
    next_day=candle(start+timedelta(days=1,minutes=1),150,50,125)
    with local() as db:
        trade=row();db.add(trade);db.commit()
        evaluate_open_signals(db,CandleProvider([next_day],start+timedelta(days=1,minutes=3)))
        assert trade.exit_reason=="DATA_GAP" and trade.result_r is None and trade.exit_at is None
        assert analytics_exclusion_reason(trade)=="DATA_GAP"
        assert "analytics_data_quality" in trade.condition_snapshot


def test_provider_failure_does_not_prematurely_quarantine_an_open_signal():
    local=database();start=datetime(2026,8,3,14,30,tzinfo=timezone.utc)
    with local() as db:
        trade=row();db.add(trade);db.commit()
        evaluate_open_signals(db,CandleProvider([],start+timedelta(days=1),status="unavailable"))
        assert trade.exit_reason=="OPEN" and trade.result_r is None


def test_cross_session_history_is_excluded_without_rewriting_the_ledger():
    trade=row();trade.exit_reason="TARGET";trade.exit_at=trade.triggered_at+timedelta(days=1)
    trade.exit_price=110;trade.result_r=10
    summary=metrics([trade])
    assert trade.result_r==10 and trade.exit_reason=="TARGET"
    assert summary["resolved_signals"]==0 and summary["cumulative_r"]==0
    assert summary["quality_exclusions"]==1


def test_deduplication_keeps_first_actual_buy_per_ticker_day():
    missed=row(signal_id="missed");missed.backend_status="MISSED";missed.exit_reason="MISSED"
    first=row(signal_id="first");first.triggered_at+=timedelta(minutes=2)
    repeat=row(signal_id="repeat");repeat.triggered_at+=timedelta(minutes=3)
    other=row(signal_id="other",ticker="QQQ");other.triggered_at+=timedelta(minutes=4)
    selected=deduplicate_positions([repeat,missed,other,first])
    assert [item.signal_id for item in selected]==["first","other"]


def test_performance_defaults_to_auto_only_true_0dte_and_deduplicated():
    local=database()
    with local() as db:
        first=row(signal_id="first")
        repeat=row(signal_id="repeat");repeat.triggered_at+=timedelta(minutes=1)
        manual=row(signal_id="manual",ticker="QQQ");manual.user_entered=True
        structured=row(signal_id="structured",ticker="IWM");structured.strategy_mode="STRUCTURED_INTRADAY"
        db.add_all([first,repeat,manual,structured]);db.commit()
        payload=performance(db=db)
        assert payload["scope"]=={"source":"LIVE","strategy_mode":"ONE_MIN_0DTE",
                                  "user_entered":False,"deduplication":"FIRST_BUY_PER_TICKER_DAY"}
        assert [item["signal_id"] for item in payload["signals"]]==["first"]
        assert payload["raw_metrics"]["total_triggered_signals"]==2
        assert payload["metrics"]["total_triggered_signals"]==1


def test_performance_paginates_newest_first_without_changing_full_metrics():
    local=database()
    with local() as db:
        for index in range(30):
            trade=row(signal_id=f"signal-{index}", ticker=f"T{index}")
            trade.triggered_at+=timedelta(minutes=index)
            db.add(trade)
        db.commit()
        payload=performance(page=2,page_size=10,db=db)
        assert payload["pagination"]=={"page":2,"page_size":10,"total_items":30,"total_pages":3}
        assert len(payload["signals"])==10
        assert payload["signals"][0]["signal_id"]=="signal-19"
        assert payload["metrics"]["total_triggered_signals"]==30
        assert payload["chart_data"]["daily"][0]["trading_date"]=="2026-08-03"


def test_chart_data_keeps_exclusions_and_option_dollars_separate():
    winner=row(signal_id="winner")
    winner.exit_reason="TARGET";winner.exit_price=102;winner.result_r=2;winner.result_return_pct=2
    winner.exit_at=winner.triggered_at+timedelta(minutes=10)
    loser=row(signal_id="loser",ticker="QQQ")
    loser.trading_date=date(2026,8,4);loser.triggered_at+=timedelta(days=1)
    loser.exit_reason="STOP";loser.exit_price=99;loser.result_r=-1;loser.result_return_pct=-1
    loser.exit_at=loser.triggered_at+timedelta(minutes=5)
    excluded=row(signal_id="excluded",ticker="IWM")
    excluded.trading_date=date(2026,8,5);excluded.triggered_at+=timedelta(days=2)
    excluded.exit_reason="TARGET";excluded.exit_price=150;excluded.result_r=50
    excluded.exit_at=excluded.triggered_at+timedelta(days=1)
    charts=performance_chart_data([winner,loser,excluded],{
        "winner":{"status":"CLOSED","pnl_dollars":30},
    })
    assert [point["cumulative_r"] for point in charts["daily"]]==[2,1,1]
    assert charts["daily"][0]["cumulative_option_pnl_dollars"]==30
    assert charts["daily"][-1]["cumulative_option_pnl_dollars"]==30
    assert charts["outcomes"]==[
        {"outcome":"TARGET","count":1},{"outcome":"STOP","count":1},
        {"outcome":"EXCLUDED","count":1},
    ]


class LiveTradierProvider:
    def status(self):
        return ProviderStatus(provider="tradier", mode="live", status="healthy", delay_seconds=0,
            latest_timestamp=datetime(2026, 8, 3, 15, tzinfo=timezone.utc), message="test")

    def candles(self, ticker, timeframe="1m"):
        return []


def structured_missed(lifecycle_id: str, minute: int) -> ParlayCandidateOut:
    return ParlayCandidateOut(symbol="SPY", rank="PLAY", direction="call", signal_status="MISSED",
        score=88, score_label="PLAY", underlying_price=103, underlying_trigger=101,
        underlying_invalidation=99, first_underlying_target=105,
        primary_action="MISSED", generated_at=datetime(2026, 8, 3, 14, minute, tzinfo=timezone.utc),
        data_freshness="live_current", lifecycle_id=lifecycle_id,
        strategy_mode="STRUCTURED_INTRADAY", strategy_version="structured-intraday-v1")


def test_distinct_same_day_lifecycles_each_get_a_performance_row():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        provider = LiveTradierProvider()
        track_candidates(db, [structured_missed("setup-1", 30)], provider)
        track_candidates(db, [structured_missed("setup-2", 45)], provider)
        rows = list(db.scalars(select(SignalPerformance).order_by(SignalPerformance.triggered_at)).all())
        assert [item.dedupe_key.rsplit(":", 1)[-1] for item in rows] == ["setup-1", "setup-2"]


def test_zero_risk_plan_is_not_added_to_the_performance_ledger():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        candidate=structured_missed("zero-risk",30)
        candidate.underlying_invalidation=candidate.underlying_trigger
        track_candidates(db,[candidate],LiveTradierProvider())
        assert list(db.scalars(select(SignalPerformance)).all())==[]


SHADOW_START = datetime(2026, 8, 3, 14, 30, tzinfo=timezone.utc)


def shadow_contract(*, bid=.40, ask=.45, stamp=SHADOW_START, symbol="SPY260803C00100000"):
    return OptionContractOut(symbol="SPY", option_symbol=symbol, normalized_symbol=symbol,
        expiration=date(2026, 8, 3), strike=100, right="call", bid=bid, ask=ask, last=(bid+ask)/2,
        volume=500, open_interest=900, timestamp=stamp, bid_timestamp=stamp, ask_timestamp=stamp,
        provider="tradier", data_mode="live", verification_status="verified",
        verification_reason="Verified against exact Tradier chain response", actionable=True)


def shadow_candidate(lifecycle="shadow-1", strategy="ONE_MIN_0DTE"):
    return ParlayCandidateOut(symbol="SPY", rank="PLAY", direction="call", signal_status="BUY",
        score=90, score_label="PLAY", underlying_price=100, contract=shadow_contract(),
        underlying_trigger=100, underlying_invalidation=99, first_underlying_target=101.5,
        primary_action="BUY", generated_at=SHADOW_START, data_freshness="live_current",
        lifecycle_id=lifecycle, strategy_mode=strategy, strategy_version="shadow-v1", actionable=True)


class ShadowProvider:
    def __init__(self, *, exit_contract=True, remaining=80):
        self.latest = SHADOW_START+timedelta(minutes=3)
        exit_stamp = SHADOW_START+timedelta(minutes=1, seconds=30)
        self.exit_contract = shadow_contract(bid=.75, ask=.80, stamp=exit_stamp) if exit_contract else None
        self.remaining = remaining
        self.chain_calls = 0

    def status(self):
        return ProviderStatus(provider="tradier", mode="live", status="healthy", delay_seconds=0,
                              latest_timestamp=self.latest, message="live test")

    def candles(self, ticker, timeframe="1m"):
        return [candle(SHADOW_START+timedelta(minutes=1), 101.5, 99.8, 101.2)]

    def option_chain(self, ticker, expiration=None):
        self.chain_calls += 1
        return [self.exit_contract] if self.exit_contract is not None else []

    def budget_status(self):
        return {"remaining": self.remaining}


def test_shadow_marks_first_ticker_day_entry_ask_and_exact_exit_bid_once():
    local = database(); provider = ShadowProvider()
    with local() as db:
        track_candidates(db, [shadow_candidate(), shadow_candidate("shadow-2", "STRUCTURED_INTRADAY")], provider)
        marks = list(db.scalars(select(AutomatedOptionMark).order_by(AutomatedOptionMark.id)).all())
        assert [(mark.mark_type, mark.selected_price) for mark in marks] == [("ENTRY", .45), ("EXIT", .75)]
        assert marks[1].quote_lag_seconds == 30 and marks[1].event_reason == "TARGET"
        assert len(list(db.scalars(select(SignalPerformance)).all())) == 2
        summary, payloads = option_shadow_results(db, list(db.scalars(select(SignalPerformance)).all()))
        assert summary["tracked_positions"] == 1 and summary["cumulative_pnl_dollars"] == 30
        shadow = next(iter(payloads.values()))
        assert shadow["status"] == "CLOSED" and shadow["return_percent"] == 66.67
        evaluate_open_signals(db, provider)
        assert len(list(db.scalars(select(AutomatedOptionMark)).all())) == 2
        assert provider.chain_calls == 1


def test_missing_exact_exit_quote_retries_then_appends_explicit_gap():
    local = database(); provider = ShadowProvider(exit_contract=False)
    with local() as db:
        track_candidates(db, [shadow_candidate()], provider)
        assert [mark.mark_type for mark in db.scalars(select(AutomatedOptionMark)).all()] == ["ENTRY"]
        provider.latest = SHADOW_START+timedelta(minutes=5)
        evaluate_open_signals(db, provider)
        marks = list(db.scalars(select(AutomatedOptionMark).order_by(AutomatedOptionMark.id)).all())
        assert len(marks) == 2 and marks[1].mark_status == "OPTION_QUOTE_GAP"
        assert marks[1].selected_price is None and "absent" in marks[1].verification_reason


def test_shadow_preserves_tradier_request_reserve_without_inventing_an_exit():
    local = database(); provider = ShadowProvider(remaining=20)
    with local() as db:
        track_candidates(db, [shadow_candidate()], provider)
        assert provider.chain_calls == 0
        provider.latest = SHADOW_START+timedelta(minutes=5)
        evaluate_open_signals(db, provider)
        marks = list(db.scalars(select(AutomatedOptionMark).order_by(AutomatedOptionMark.id)).all())
        assert provider.chain_calls == 0 and marks[-1].mark_status == "OPTION_QUOTE_GAP"
        assert "request reserve" in marks[-1].verification_reason


def test_shadow_uses_fresh_cached_chain_even_when_request_reserve_is_engaged():
    class CachedShadowProvider(ShadowProvider):
        def cached_option_chain(self, ticker, expiration):
            return [self.exit_contract]

    local = database(); provider = CachedShadowProvider(remaining=0)
    with local() as db:
        track_candidates(db, [shadow_candidate()], provider)
        marks = list(db.scalars(select(AutomatedOptionMark).order_by(AutomatedOptionMark.id)).all())
        assert provider.chain_calls == 0
        assert [(mark.mark_type, mark.mark_status) for mark in marks] == [
            ("ENTRY", "QUOTED"), ("EXIT", "QUOTED")]
