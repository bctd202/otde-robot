from datetime import date, datetime, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BacktestRun, SignalPerformance
from app.services.parlay import PRODUCTION_TIMEFRAME, evaluate_underlying_setup
from app.services.performance import SESSION_CUTOFF, STRATEGY_SNAPSHOT, STRATEGY_VERSION, update_outcome

NY = ZoneInfo("America/New_York")


def replay_evaluation(candles: list, underlying_price: float):
    """Expose the same completed-candle production evaluator used by the scanner."""
    return evaluate_underlying_setup(candles, underlying_price)


def run_backtest(db: Session, provider, start: date, end: date, tickers: list[str]) -> BacktestRun:
    if db.scalar(select(BacktestRun).where(BacktestRun.status.in_(["QUEUED", "RUNNING"]))) is not None:
        raise ValueError("A backtest is already running")
    now = datetime.now(timezone.utc)
    run = BacktestRun(id=str(uuid4()), requested_start=start, requested_end=end, tickers=tickers,
        strategy_snapshot=STRATEGY_SNAPSHOT, status="RUNNING", warnings=[], failures={}, started_at=now)
    db.add(run)
    db.commit()
    available: list[date] = []
    for ticker in tickers:
        try:
            candles = provider.historical_candles(ticker, PRODUCTION_TIMEFRAME, start, end)
        except Exception as exc:
            run.failures = {**run.failures, ticker: type(exc).__name__}
            continue
        candles = sorted([c for c in candles if start <= c.timestamp.astimezone(NY).date() <= end],
                         key=lambda candle: candle.timestamp)
        if len(candles) < 8:
            run.failures = {**run.failures, ticker: "Historical candles unavailable or incomplete"}
            continue
        available.extend(c.timestamp.astimezone(NY).date() for c in candles)
        active = None
        for index in range(7, len(candles)):
            candle, stamp = candles[index], candles[index].timestamp
            if active:
                cutoff = stamp.astimezone(NY).time() >= SESSION_CUTOFF
                update_outcome(active, candle.high, candle.low, candle.close, stamp, cutoff=cutoff)
                active.last_evaluated_at = stamp.astimezone(timezone.utc)
                if active.exit_reason != "OPEN":
                    active = None
                continue
            # This prefix contains only candles completed at this replay point.
            setup = replay_evaluation(candles[:index+1], candle.close)
            if setup.direction is None or not setup.confirmed:
                continue
            key = f"{run.id}:{ticker}:{stamp.isoformat()}"
            active = SignalPerformance(signal_id=str(uuid4()), source="BACKTEST", dedupe_key=key,
                backtest_run_id=run.id, ticker=ticker, direction=setup.direction.upper(), backend_status="BUY",
                setup_type="directional-liquidity", strategy_version=STRATEGY_VERSION,
                strategy_snapshot=STRATEGY_SNAPSHOT,
                condition_snapshot={"reasons": setup.reasons, "completed_candle_count": index+1,
                                    "production_directional_checks": setup.checks,
                                    "extension_r": setup.extension_r, "confirmed": setup.confirmed},
                trading_date=stamp.astimezone(NY).date(), triggered_at=stamp.astimezone(timezone.utc),
                entry_price=setup.trigger, stop_price=setup.stop, target_price=setup.target,
                exit_reason="OPEN", result_r=None, mfe_r=0, mae_r=0, score=min(100, 42+setup.checks*8),
                user_entered=False, option_snapshot=None, conservative_same_candle=False,
                created_at=now, updated_at=now, last_evaluated_at=stamp.astimezone(timezone.utc))
            db.add(active)
        if active and active.exit_reason == "OPEN":
            last = candles[-1]
            update_outcome(active, last.close, last.close, last.close, last.timestamp, cutoff=True)
            active.last_evaluated_at = last.timestamp.astimezone(timezone.utc)
    if available:
        run.actual_start, run.actual_end = min(available), max(available)
    run.status = "PARTIAL" if run.failures and available else "FAILED" if run.failures else "COMPLETED"
    if run.failures:
        run.warnings = ["Some tickers had partial or unavailable Tradier history."]
    run.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    return run
