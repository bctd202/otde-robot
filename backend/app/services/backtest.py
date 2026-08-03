from datetime import date, datetime, time, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import BacktestRun, SignalPerformance
from app.services.parlay import _directional_plan
from app.services.performance import STRATEGY_SNAPSHOT, STRATEGY_VERSION, update_outcome
NY=ZoneInfo("America/New_York")

def run_backtest(db:Session,provider,start:date,end:date,tickers:list[str])->BacktestRun:
    if db.scalar(select(BacktestRun).where(BacktestRun.status.in_(["QUEUED","RUNNING"]))) is not None: raise ValueError("A backtest is already running")
    now=datetime.now(timezone.utc); run=BacktestRun(id=str(uuid4()),requested_start=start,requested_end=end,tickers=tickers,
        strategy_snapshot=STRATEGY_SNAPSHOT,status="RUNNING",warnings=[],failures={},started_at=now)
    db.add(run);db.commit(); available: list[date]=[]
    for ticker in tickers:
        try: candles=provider.historical_candles(ticker,"5m",start,end)
        except Exception as exc: run.failures={**run.failures,ticker:type(exc).__name__};continue
        candles=sorted([c for c in candles if start<=c.timestamp.astimezone(NY).date()<=end],key=lambda c:c.timestamp)
        if len(candles)<8: run.failures={**run.failures,ticker:"Historical candles unavailable or incomplete"};continue
        available.extend(c.timestamp.astimezone(NY).date() for c in candles); active=None
        for index in range(7,len(candles)):
            candle=candles[index]; stamp=candle.timestamp
            if active:
                update_outcome(active,candle.high,candle.low,stamp,stamp.astimezone(NY).time()>=time(15,45))
                if active.exit_reason!="OPEN": active=None
                continue
            # Only this chronological prefix is exposed to the production directional engine.
            direction,checks,reasons,trigger,stop,confirmed=_directional_plan(candles[:index+1])
            if direction is None or not confirmed: continue
            risk=max(abs(trigger-stop),candle.close*.002); target=trigger+risk*(1.5 if direction=="call" else -1.5)
            key=f"{run.id}:{ticker}:{stamp.isoformat()}"; active=SignalPerformance(signal_id=str(uuid4()),source="BACKTEST",dedupe_key=key,
                backtest_run_id=run.id,ticker=ticker,direction=direction.upper(),backend_status="BUY",setup_type="directional-liquidity",
                strategy_version=STRATEGY_VERSION,strategy_snapshot=STRATEGY_SNAPSHOT,condition_snapshot={"reasons":reasons,"completed_candle_count":index+1,"production_directional_checks":checks},
                trading_date=stamp.astimezone(NY).date(),triggered_at=stamp.astimezone(timezone.utc),entry_price=trigger,stop_price=stop,target_price=target,
                exit_reason="OPEN",result_r=None,mfe_r=0,mae_r=0,score=min(100,42+checks*8),user_entered=False,option_snapshot=None,
                conservative_same_candle=False,created_at=now,updated_at=now);db.add(active)
        if active and active.exit_reason=="OPEN": update_outcome(active,candles[-1].close,candles[-1].close,candles[-1].timestamp,True)
    if available: run.actual_start=min(available);run.actual_end=max(available)
    run.status="PARTIAL" if run.failures and available else "FAILED" if run.failures else "COMPLETED"
    if run.failures: run.warnings=["Some tickers had partial or unavailable Tradier history."]
    run.completed_at=datetime.now(timezone.utc);db.commit();db.refresh(run);return run
