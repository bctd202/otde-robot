from datetime import date, datetime, timedelta, timezone
from app.db.models import SignalPerformance
from app.services.performance import metrics, update_outcome

def row(direction="CALL"):
    now=datetime(2026,8,3,14,30,tzinfo=timezone.utc)
    return SignalPerformance(signal_id="x",source="LIVE",dedupe_key="x",ticker="SPY",direction=direction,backend_status="BUY",setup_type="directional-liquidity",strategy_version="v",strategy_snapshot={},condition_snapshot={},trading_date=date(2026,8,3),triggered_at=now,entry_price=100,stop_price=99,target_price=101.5,exit_reason="OPEN",mfe_r=0,mae_r=0,score=90,user_entered=False,conservative_same_candle=False,created_at=now,updated_at=now,last_evaluated_at=now)

def test_target_stop_and_same_candle_conservative_resolution():
    target=row();update_outcome(target,101.5,100.2,101.5,target.triggered_at+timedelta(minutes=5));assert target.exit_reason=="TARGET" and target.result_r==1.5
    stop=row();update_outcome(stop,100.2,99,99,stop.triggered_at+timedelta(minutes=5));assert stop.exit_reason=="STOP" and stop.result_r==-1
    both=row();update_outcome(both,102,98,99,both.triggered_at+timedelta(minutes=5));assert both.exit_reason=="STOP" and both.conservative_same_candle

def test_timed_exit_excursions_duration_and_open_metric_exclusion():
    closed=row();update_outcome(closed,100.8,99.6,100.2,closed.triggered_at+timedelta(minutes=15),cutoff=True)
    opened=row();opened.signal_id="open";opened.dedupe_key="open"
    summary=metrics([closed,opened])
    assert closed.result_r==0.2 and closed.mfe_r==0.8 and closed.mae_r==0.4 and closed.duration_minutes==15
    assert summary["open_signals"]==1 and summary["average_r"]==0.2 and summary["win_rate"]==100

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.session import Base
from app.schemas.market import CandleOut, ProviderStatus
from app.services.performance import evaluate_open_signals

class CandleProvider:
    def __init__(self, candles, latest): self.rows,self.latest=candles,latest
    def status(self): return ProviderStatus(provider="test",mode="mock",status="healthy",delay_seconds=0,latest_timestamp=self.latest,message="test")
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
