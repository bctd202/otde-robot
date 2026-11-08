"""Session-isolated replay; historical option eligibility is never synthesized."""
from datetime import date, datetime, timedelta, timezone
import math
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BacktestRun, SignalPerformance
from app.schemas.market import OptionContractOut
from app.services.contracts import annotate_chain
from app.services.market_calendar import NY, REGULAR_OPEN
from app.services.one_minute_gate import GateResult, evaluate as entry_gate
from app.services.parlay import PRODUCTION_TIMEFRAME, STRATEGY_VERSION, _eligible_contract, evaluate_underlying_setup
from app.services.performance import STRATEGY_SNAPSHOT, _mark_data_gap, update_outcome
from app.services.research_session_policy import session_limits
from app.services.result_model import VERSION as RESULT_VERSION, utc
from app.services.session_candles import session_candles


def replay_evaluation(candles: list, underlying_price: float):
    return evaluate_underlying_setup(candles, underlying_price)


def _historical_gate(provider, ticker, setup, decision):
    """Only archived chains qualify; never call today's option_chain."""
    method = getattr(provider, "historical_option_chain", None)
    if not callable(method):
        return None, None
    raw = method(ticker, decision)
    if not raw:
        return None, None
    rows = [c.model_copy(deep=True) for c in raw if isinstance(c,OptionContractOut) and all(t is not None and
        decision-timedelta(minutes=2) <= utc(t) <= decision
        for t in (c.timestamp, c.bid_timestamp, c.ask_timestamp))]
    if not rows:
        return None, None
    chain = annotate_chain(rows, ticker, decision)
    contract, _ = _eligible_contract(chain, setup.direction, setup.target, session_day=decision.astimezone(NY).date())
    return (contract, entry_gate(setup, contract)) if contract else (None, "REJECTED")


def _valid(candle) -> bool:
    return (all(math.isfinite(p) and p > 0 for p in (candle.open,candle.high,candle.low,candle.close))
            and candle.low <= min(candle.open,candle.close) <= max(candle.open,candle.close) <= candle.high
            and candle.volume >= 0)


def run_backtest(db: Session, provider, start: date, end: date, tickers: list[str]) -> BacktestRun:
    if db.scalar(select(BacktestRun).where(BacktestRun.status.in_(["QUEUED", "RUNNING"]))) is not None:
        raise ValueError("A backtest is already running")
    now = datetime.now(timezone.utc)
    diagnostics = {"verified_buy_entries": 0, "underlying_only_entries": 0,
                   "rejected_live_gate": 0, "input_gaps": 0}
    run = BacktestRun(id=str(uuid4()), requested_start=start, requested_end=end, tickers=tickers,
        strategy_snapshot={**STRATEGY_SNAPSHOT, "result_model_version": RESULT_VERSION,
            "entry_basis": "NEXT_CONSECUTIVE_SAME_SESSION_BAR_OPEN", "historical_option_gate": "REQUIRED_FOR_BUY",
            "diagnostics": diagnostics}, status="RUNNING", warnings=[], failures={}, started_at=now)
    db.add(run); db.commit()
    available: list[date] = []
    for ticker in tickers:
        try:
            candles = list(provider.historical_candles(ticker, PRODUCTION_TIMEFRAME, start, end))
        except Exception as exc:
            run.failures = {**run.failures, ticker: type(exc).__name__}
            continue
        days = sorted({utc(c.timestamp).astimezone(NY).date() for c in candles
                       if start <= utc(c.timestamp).astimezone(NY).date() <= end})
        used_days = 0
        for day in days:
            try:
                limits = session_limits(day)
            except ValueError:
                continue
            rows = session_candles([c for c in candles if _valid(c)], limits["close"]-timedelta(minutes=1))
            if len(rows) < 9:
                continue
            available.append(day); used_days += 1
            opening = datetime.combine(day, REGULAR_OPEN, NY).astimezone(timezone.utc)
            for index in range(7, len(rows)-1):
                confirming, following = rows[index], rows[index+1]
                decision = utc(following.timestamp)
                if decision > limits["timed_exit_candle"]:
                    break
                prefix = rows[:index+1]
                if (utc(rows[0].timestamp) != opening or utc(confirming.timestamp)+timedelta(minutes=1) != decision
                        or any(utc(b.timestamp) != opening+timedelta(minutes=i) for i,b in enumerate(prefix))):
                    diagnostics["input_gaps"] += 1
                    continue
                setup = replay_evaluation(prefix, following.open)
                if setup.direction is None or not setup.confirmed:
                    continue
                if setup.extension_r > 1.35:
                    diagnostics["rejected_live_gate"] += 1
                    continue
                try:
                    contract, gate = _historical_gate(provider, ticker, setup, decision)
                except (KeyError, TypeError, ValueError, RuntimeError):
                    contract, gate = None, None
                if gate == "REJECTED" or (isinstance(gate,GateResult) and gate.signal != "BUY"):
                    diagnostics["rejected_live_gate"] += 1
                    continue
                entry = following.open
                if not (setup.stop < entry < setup.target if setup.direction == "call" else setup.target < entry < setup.stop):
                    diagnostics["rejected_live_gate"] += 1
                    continue
                qualified = contract is not None and isinstance(gate,GateResult)
                diagnostics["verified_buy_entries" if qualified else "underlying_only_entries"] += 1
                definition = {"version": RESULT_VERSION, "basis": "NEXT_BAR_OPEN_BENCHMARK_NOT_OPTION_FILL",
                    "underlying_trigger": setup.trigger, "entry_quote_price": entry,
                    "entry_quote_at": decision.isoformat(), "confirmation_candle_at": utc(confirming.timestamp).isoformat(),
                    "first_evaluation_candle_at": decision.isoformat(), "partial_entry_minute": False,
                    "quality_error": None}
                active = SignalPerformance(signal_id=str(uuid4()), source="BACKTEST",
                    dedupe_key=f"{run.id}:{ticker}:{day}", backtest_run_id=run.id, ticker=ticker,
                    direction=setup.direction.upper(), backend_status="BUY" if qualified else "UNDERLYING_ONLY",
                    setup_type="directional-liquidity", strategy_mode="ONE_MIN_0DTE", strategy_version=STRATEGY_VERSION,
                    strategy_snapshot={**STRATEGY_SNAPSHOT, "result_model": definition,
                        "historical_option_gate": "ARCHIVED_QUOTES" if qualified else "UNAVAILABLE_NOT_A_LIVE_BUY"},
                    condition_snapshot={"reasons": setup.reasons, "completed_candle_count": len(prefix),
                        "production_directional_checks": setup.checks, "extension_r": setup.extension_r,
                        "full_buy_gate_verified": qualified}, trading_date=day, triggered_at=decision,
                    entry_price=entry, stop_price=setup.stop, target_price=setup.target,
                    exit_reason="OPEN", result_r=None, mfe_r=0, mae_r=0,
                    score=round(gate.score,1) if isinstance(gate,GateResult) else 0, user_entered=False,
                    option_snapshot=contract.model_dump(mode="json") if qualified else None,
                    conservative_same_candle=False, created_at=now, updated_at=now,
                    last_evaluated_at=utc(confirming.timestamp))
                db.add(active)
                expected = decision
                for bar in rows[index+1:]:
                    if utc(bar.timestamp) != expected:
                        _mark_data_gap(active, now, "MISSING_POST_ENTRY_CANDLE")
                        break
                    update_outcome(active, bar.high, bar.low, bar.close, utc(bar.timestamp),
                                   cutoff=utc(bar.timestamp) >= limits["timed_exit_candle"])
                    active.last_evaluated_at = utc(bar.timestamp)
                    expected += timedelta(minutes=1)
                    if active.exit_reason != "OPEN":
                        break
                if active.exit_reason == "OPEN":
                    _mark_data_gap(active, now, "MISSING_SESSION_CUTOFF_CANDLE")
                break
        if not used_days:
            run.failures = {**run.failures, ticker: "No complete regular-session entry history"}
    if available:
        run.actual_start, run.actual_end = min(available), max(available)
    run.strategy_snapshot = {**run.strategy_snapshot, "diagnostics": diagnostics,
        "evidence_mode": "UNDERLYING_ONLY" if diagnostics["underlying_only_entries"] or not callable(
            getattr(provider,"historical_option_chain",None)) else "ARCHIVED_OPTION_GATE"}
    warnings = []
    if diagnostics["underlying_only_entries"]:
        warnings.append("Underlying-only observations: historical option eligibility is unavailable. These are not verified live BUYs or option returns.")
    if diagnostics["input_gaps"]:
        warnings.append("Missing entry-context candles were excluded; session gaps are not filled.")
    if run.failures:
        warnings.append("Some tickers had partial or unavailable provider history.")
    run.warnings = warnings
    run.status = "PARTIAL" if run.failures and available else "FAILED" if run.failures else "COMPLETED"
    run.completed_at = datetime.now(timezone.utc)
    db.commit(); db.refresh(run)
    return run
