from datetime import date, datetime, timedelta, timezone
from app.db.models import SignalPerformance
from app.services.performance import metrics, update_outcome

def row(direction="CALL"):
    now=datetime(2026,8,3,14,30,tzinfo=timezone.utc)
    return SignalPerformance(signal_id="x",source="LIVE",dedupe_key="x",ticker="SPY",direction=direction,backend_status="BUY",setup_type="directional-liquidity",strategy_version="v",strategy_snapshot={},condition_snapshot={},trading_date=date(2026,8,3),triggered_at=now,entry_price=100,stop_price=99,target_price=101.5,exit_reason="OPEN",mfe_r=0,mae_r=0,score=90,user_entered=False,conservative_same_candle=False,created_at=now,updated_at=now)

def test_target_stop_and_same_candle_conservative_resolution():
    target=row();update_outcome(target,101.5,100.2,target.triggered_at+timedelta(minutes=5));assert target.exit_reason=="TARGET" and target.result_r==1.5
    stop=row();update_outcome(stop,100.2,99,stop.triggered_at+timedelta(minutes=5));assert stop.exit_reason=="STOP" and stop.result_r==-1
    both=row();update_outcome(both,102,98,both.triggered_at+timedelta(minutes=5));assert both.exit_reason=="STOP" and both.conservative_same_candle

def test_timed_exit_excursions_duration_and_open_metric_exclusion():
    closed=row();update_outcome(closed,100.8,99.6,closed.triggered_at+timedelta(minutes=15),cutoff=True)
    opened=row();opened.signal_id="open";opened.dedupe_key="open"
    summary=metrics([closed,opened])
    assert closed.result_r==0.2 and closed.mfe_r==0.8 and closed.mae_r==0.4 and closed.duration_minutes==15
    assert summary["open_signals"]==1 and summary["average_r"]==0.2 and summary["win_rate"]==100
