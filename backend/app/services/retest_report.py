"""Read-only bounded research dashboard and preregistered evaluation gates."""
from datetime import date, datetime, timedelta, timezone
import math

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import RetestAccount, RetestEvent, RetestObservation, RetestOpportunity, RetestPosition, RetestRun
from app.services.market_calendar import NY
from app.services.option_research import utc
from app.services.research_session_policy import session_limits
from app.services.retest_evaluation import paired_block_bootstrap
from app.services.retest_trials import ARMS, KEY, SCENARIOS, account_key, balance


def summary(db: Session, *, page: int = 1, view: str = "accounts", now: datetime | None = None) -> dict:
    now = utc(now or datetime.now(timezone.utc))
    run = db.get(RetestRun, KEY)
    if run is None:
        return {"status": "NOT_ACTIVATED", "paper_only": True, "run_key": KEY,
                "note": "Prepared only. Separate operator approval/activation required; no accounts funded."}
    if view not in ("accounts", "opportunities"):
        raise ValueError("Unknown research view")
    dates = [date.fromisoformat(d) for d in run.policy["sessions"]]
    accounts = list(db.scalars(select(RetestAccount).where(RetestAccount.run_key == KEY)).all())
    daily: dict[str, dict] = {a.key: {} for a in accounts}
    peaks = {a.key: 200000 for a in accounts}
    drawdown = {a.key: 0 for a in accounts}
    gap_days: dict[str, set[date]] = {a.key: set() for a in accounts}
    observations: dict[date, set] = {}
    input_n = 0
    universe = run.policy["configuration"]["universe"]
    latest = None
    # Do not materialize all historical quote JSON in a polling request.
    rows = db.execute(select(RetestObservation.evaluation_at, RetestObservation.observed_at, RetestObservation.detail)
        .where(RetestObservation.run_key == KEY).order_by(RetestObservation.evaluation_at)
        .execution_options(yield_per=50))
    for evaluation, at, detail in rows:
        evaluation, at = utc(evaluation), utc(at)
        day = evaluation.astimezone(NY).date()
        if day not in dates:
            continue
        limits = session_limits(day)
        opening = datetime.combine(day, datetime.min.time().replace(hour=9,minute=30), NY)
        if not opening <= evaluation < limits["close"]:
            continue
        observations.setdefault(day, set()).add(evaluation)
        input_n += sum(detail.get("inputs", {}).get(t, False) for t in universe)
        latest = {"at": at.isoformat(), "accounts": detail["accounts"]}
        for a in accounts:
            equity = detail["accounts"].get(a.key, {}).get("equity_cents")
            if equity is None:
                gap_days[a.key].add(day)
            else:
                peaks[a.key] = max(peaks[a.key], equity)
                drawdown[a.key] = max(drawdown[a.key], peaks[a.key]-equity)
            daily[a.key][day] = {"at": at, "equity_cents": equity}
    expected = 0; full_minutes = {}
    for day in dates:
        limits = session_limits(day)
        opening = datetime.combine(day, datetime.min.time().replace(hour=9,minute=30), NY)
        full_minutes[day] = int((limits["close"]-opening).total_seconds()/60)
        elapsed = max(0, min(full_minutes[day], int((now-opening).total_seconds()/60)))
        expected += elapsed*len(universe)
    candle_coverage = round(input_n/expected*100, 3) if expected else None
    verifications = list(db.scalars(select(RetestEvent.detail['input_complete'].as_boolean()).join(RetestPosition,
        RetestPosition.id == RetestEvent.position_id).where(RetestEvent.run_key == KEY,
            RetestEvent.kind == 'RETEST_VERIFICATION', RetestPosition.scenario == 'opportunity')))
    retest_coverage = sum(bool(d) for d in verifications)/len(verifications)*100 if verifications else None
    plans = db.execute(select(RetestOpportunity.frozen['retest_setup'].as_string().is_not(None),
        RetestOpportunity.frozen['freeze_error'].as_string()).where(RetestOpportunity.run_key == KEY,
        RetestOpportunity.mode == 'ONE_MIN_0DTE')).all()
    planning_coverage = sum(valid or error == 'ENTRY_CUTOFF' for valid,error in plans)/len(plans)*100 if plans else None
    coverages = [v for v in (candle_coverage,retest_coverage,planning_coverage) if v is not None]
    coverage = min(coverages) if coverages else None
    # Request-based coverage: capacity/verification failures cannot disappear by
    # selecting only closed trades. Count the first event of each kind/position.
    counts = {(akey, kind): count for akey, kind, count in db.execute(select(
        RetestEvent.account_key, RetestEvent.kind, func.count(func.distinct(RetestEvent.position_id)))
        .where(RetestEvent.run_key == KEY).group_by(RetestEvent.account_key, RetestEvent.kind))}
    metrics = []
    daily_changes = {}
    for a in accounts:
        unknown = db.scalar(select(func.count()).select_from(RetestPosition).where(
            RetestPosition.account_key == a.key, RetestPosition.status.in_(("OPEN", "EXIT_PENDING", "UNPRICED")))) or 0
        equity_values = []; changes = []; previous = 200000
        complete = not unknown
        for day in dates:
            point = daily[a.key].get(day)
            limits = session_limits(day)
            valid = (point is not None and point["equity_cents"] is not None and
                     limits["close"] <= point["at"] <= limits["close"]+timedelta(minutes=3) and
                     day not in gap_days[a.key] and len(observations.get(day, set())) == full_minutes[day])
            value = point["equity_cents"] if point else None
            change = (value-previous)/100 if valid and previous is not None else None
            changes.append(change); equity_values.append({"date": day.isoformat(), "equity_cents": value,
                                                          "complete": bool(valid)})
            previous = value if valid else None
            complete = complete and bool(valid)
        daily_changes[a.key] = changes
        entry_n = counts.get((a.key, "ENTRY_REQUEST"), 0)
        exit_n = counts.get((a.key, "EXIT_REQUEST"), 0)
        settled, unsettled = balance(db, a.key)
        completed_one_minute = db.scalar(select(func.count(func.distinct(RetestEvent.position_id)))
            .join(RetestPosition, RetestPosition.id == RetestEvent.position_id)
            .join(RetestOpportunity, RetestOpportunity.id == RetestPosition.opportunity_id)
            .where(RetestEvent.run_key == KEY, RetestEvent.account_key == a.key,
                   RetestEvent.kind == "EXIT", RetestOpportunity.mode == "ONE_MIN_0DTE")) or 0
        metrics.append({"key": a.key, "arm": a.arm, "scenario": a.scenario,
            "settled_cents": settled, "unsettled_cents": unsettled, "unresolved": unknown,
            "entry_requests": entry_n, "exit_requests": exit_n,
            "entry_quote_coverage": counts.get((a.key, "ENTRY_QUOTE_AVAILABLE"), 0)/entry_n*100 if entry_n else None,
            "exit_quote_coverage": counts.get((a.key, "EXIT_QUOTE_AVAILABLE"), 0)/exit_n*100 if exit_n else None,
            "completed_trades": counts.get((a.key, "EXIT"), 0),
            "completed_one_minute_trades": completed_one_minute,
            "complete": complete, "net_pnl_cents": previous-200000 if complete and previous is not None else None,
            "max_drawdown_cents": drawdown[a.key] if complete else None,
            "observed_drawdown_lower_bound_cents": drawdown[a.key], "daily": equity_values})
    by_key = {m["key"]: m for m in metrics}
    opportunities = db.scalar(select(func.count()).select_from(RetestOpportunity).where(
        RetestOpportunity.run_key == KEY, RetestOpportunity.mode == "ONE_MIN_0DTE")) or 0
    drift = bool(db.scalar(select(RetestEvent.id).where(RetestEvent.run_key == KEY, RetestEvent.kind == "PROTOCOL_DRIFT")))
    end = session_limits(dates[-1])["close"]
    adequate = now >= end and opportunities >= 100 and coverage is not None and coverage >= 95 and not drift
    gates = {}; intervals = {}
    for scenario in SCENARIOS:
        c, t = (by_key[account_key(arm, scenario)] for arm in ARMS)
        good_quotes = all(c[k] is not None and t[k] is not None and min(c[k],t[k]) >= 90 and
                          abs(c[k]-t[k]) <= 5 for k in ("entry_quote_coverage", "exit_quote_coverage"))
        enough = adequate and good_quotes and t["completed_one_minute_trades"] >= 30 and c["complete"] and t["complete"]
        if not enough:
            gates[scenario] = {"status": "INCONCLUSIVE", "quote_coverage_pass": good_quotes}
            continue
        control, treatment = (daily_changes[account_key(arm, scenario)] for arm in ARMS)
        advantage = [tv-cv for cv,tv in zip(control,treatment)]
        robust_t = sum(treatment)-sum(sorted(treatment, reverse=True)[:3])
        robust_adv = sum(advantage)-sum(sorted(advantage, reverse=True)[:3])
        conditions = {"positive_net": t["net_pnl_cents"] > 0,
            "positive_advantage": t["net_pnl_cents"] > c["net_pnl_cents"],
            "drawdown": t["max_drawdown_cents"] <= min(20000,c["max_drawdown_cents"]),
            "remove_best_three_positive": robust_t > 0,
            "remove_three_advantage_sessions_positive": robust_adv > 0}
        gates[scenario] = {"status": "PASS" if all(conditions.values()) else "DID_NOT_MEET_CRITERIA", **conditions,
            "robust_treatment_dollars": robust_t, "robust_advantage_dollars": robust_adv}
        intervals[scenario] = paired_block_bootstrap(control,treatment)
    statuses = [g["status"] for g in gates.values()]
    verdict = "INCONCLUSIVE" if "INCONCLUSIVE" in statuses else "PASS" if all(s == "PASS" for s in statuses) else "DID_NOT_MEET_CRITERIA"
    query = select(RetestPosition).join(RetestOpportunity).where(RetestOpportunity.run_key == KEY)
    query = query.where(RetestPosition.account_key.is_(None) if view == "opportunities" else RetestPosition.account_key.is_not(None))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    pages = max(1, math.ceil(total/20)); page = min(max(1,page),pages)
    visible = db.scalars(query.order_by(RetestPosition.id.desc()).offset((page-1)*20).limit(20)).all()
    tickers = {oid:ticker for oid,ticker in db.execute(select(RetestOpportunity.id,RetestOpportunity.ticker).where(
        RetestOpportunity.id.in_([p.opportunity_id for p in visible]))).all()}
    return {"status": "COMPLETE" if now >= end else "COLLECTING", "paper_only": True,
        "run_key": KEY, "activated_at": utc(run.activated_at).isoformat(), "policy": run.policy,
        "spec_hash": run.policy["spec_hash"], "protocol_drift": drift, "baseline_opportunities": opportunities,
        "input_coverage": coverage, "candle_coverage": candle_coverage, "retest_input_coverage": retest_coverage,
        "planning_coverage": planning_coverage, "input_observations": input_n, "expected_inputs": expected,
        "accounts": metrics, "latest": latest, "verdict": verdict, "gates": gates, "uncertainty": intervals,
        "positions": [{"id": p.id, "account": p.account_key, "arm": p.arm, "scenario": p.scenario,
                       "ticker": tickers[p.opportunity_id], "status": p.status,
                       "detail": {k:p.detail.get(k) for k in ("reason","entry_at","exit_at","entry_debit_cents",
                           "net_pnl_cents","opportunity_outcome")}} for p in visible],
        "pagination": {"page": page, "pages": pages, "total": total}, "view": view,
        "note": "Paper evidence only. Opportunity rows ignore cash limits and are not portfolio returns. "
                "Missing valuations make complete drawdown/performance claims inconclusive. Accounts are never summed."}
