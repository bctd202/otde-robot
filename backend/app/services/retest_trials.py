"""Prospective paired paper accounts; dormant until an explicit operator activation.

Caller owns the transaction. No broker orders, historical imports, account resets,
or writes to existing research tables. Reads never initialize or advance accounts.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (ForwardPaperAccount, RetestAccount, RetestEvent, RetestObservation,
                           RetestOpportunity, RetestPosition, RetestRun)
from app.schemas.market import CandleOut, OptionContractOut
from app.services.contracts import is_verified_actionable_contract, validate_exit_quote
from app.services.forward_account import KEY as MAIN_KEY, cents, settlement_at
from app.services.market_calendar import NY, market_session
from app.services.option_research import utc
from app.services.research_session_policy import VERSION as SESSION_VERSION, session_limits
from app.services.retest_evaluation import evaluation_sessions
from app.services.retest_research import FrozenSetup, TimingState, advance, canonical, stamp, start

KEY = "breakout-retest-v1"
ARMS = ("control", "treatment")
SCENARIOS = ("base", "stress")
OCCUPIED = ("WAIT_RETEST", "PENDING_ENTRY", "OPEN", "EXIT_PENDING", "UNPRICED")
HELD = ("OPEN", "EXIT_PENDING", "UNPRICED")
MODES = ("ONE_MIN_0DTE", "STRUCTURED_INTRADAY")


def configuration() -> dict:
    settings = get_settings()
    return {"provider": settings.market_data_provider, "universe": settings.parlay_symbol_list,
            "paper_only": settings.paper_only}


def code_hash() -> str:
    root = Path(__file__).parent
    names = ("retest_trials.py", "retest_research.py", "retest_evaluation.py", "retest_report.py",
             "research_session_policy.py", "parlay.py", "structured_intraday.py", "contracts.py",
             "market_calendar.py", "forward_account.py")
    paths = [root/name for name in names]+[root.parent/'market_data'/name for name in ('tastytrade.py','cached.py')]
    return hashlib.sha256(b"".join(p.read_bytes() for p in paths)).hexdigest()


def account_key(arm: str, scenario: str) -> str:
    return f"{KEY}:{arm}:{scenario}"


def event(db: Session, key: str, now: datetime, kind: str, *, position=None, account=None,
          settled=0, unsettled=0, realized=0, detail=None) -> None:
    if db.scalar(select(RetestEvent.id).where(RetestEvent.run_key == KEY, RetestEvent.event_key == key)):
        return
    db.add(RetestEvent(run_key=KEY, event_key=key, at=now, kind=kind,
        position_id=position.id if position else None,
        account_key=position.account_key if position else account,
        settled=settled, unsettled=unsettled, realized=realized, detail=detail or {}))
    db.flush()


def activate(db: Session, *, revision: str, now: datetime) -> RetestRun:
    """Explicit operator-only operation, one caller-owned transaction; never startup/GET."""
    now = stamp(now)
    existing = db.get(RetestRun, KEY)
    if existing:
        accounts = db.scalars(select(RetestAccount).where(RetestAccount.run_key == KEY)).all()
        if len(accounts) != 4 or any(not db.scalar(select(RetestEvent.id).where(
                RetestEvent.event_key == f"funding:{a.key}", RetestEvent.run_key == KEY)) for a in accounts):
            raise ValueError("Partial activation; manual review required")
        return existing
    if market_session(now) == "regular":
        raise ValueError("Activate outside the market session; no mid-session cohort")
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Exact reviewed Git revision required")
    config = configuration()
    if not config["paper_only"] or config["provider"] != "tastytrade":
        raise ValueError("Explicit Tastytrade paper configuration required")
    main = db.get(ForwardPaperAccount, MAIN_KEY)
    if main is None:
        raise ValueError("Existing main account policy required; never create it here")
    baseline = dict(main.policy)
    if (baseline.get("required_provider") != "tastytrade" or baseline.get("quantity") != 1
            or baseline.get("max_positions") != 3 or baseline.get("starting_cash_cents") != 200000):
        raise ValueError("Main policy differs from reviewed control; re-review required")
    dates = [d.isoformat() for d in evaluation_sessions(now)]
    policy = {"version": KEY, "baseline_account": MAIN_KEY, "baseline_policy": baseline,
        "session_version": SESSION_VERSION, "revision": revision, "code_hash": code_hash(),
        "configuration": config, "sessions": dates, "starting_cash_cents": 200000,
        "stress_slippage_premium_cents": 3, "pending_consumes_slot": False,
        "selection": "FIRST_QUALIFIED_BUY_PER_TICKER_DAY_ACROSS_ENGINES",
        "bootstrap": "paired-overlapping-noncircular-five-session-blocks-v1",
        "input_coverage_denominator": "every scheduled minute x frozen base universe, including outages",
        "input_coverage_rule": "minimum of candle, first-opportunity planning, and retest-decision input coverage",
        "entry_coverage_denominator": "all later-quote entry requests, not fills",
        "exit_coverage_denominator": "all exit requests including overdue/unknown exits",
        "live_orders": False}
    policy["spec_hash"] = hashlib.sha256(canonical(policy).encode()).hexdigest()
    run = RetestRun(key=KEY, activated_at=now, processed_at=now, revision=0, policy=policy)
    db.add(run); db.flush()
    for arm in ARMS:
        for scenario in SCENARIOS:
            key = account_key(arm, scenario)
            db.add(RetestAccount(key=key, run_key=KEY, arm=arm, scenario=scenario)); db.flush()
            event(db, f"funding:{key}", now, "FUNDING", account=key, settled=200000,
                  detail={"policy": policy, "scenario": scenario, "independent_account": True})
    return run


def active(db: Session) -> bool:
    return db.get(RetestRun, KEY) is not None


def balance(db: Session, key: str) -> tuple[int, int]:
    row = db.execute(select(func.coalesce(func.sum(RetestEvent.settled), 0),
        func.coalesce(func.sum(RetestEvent.unsettled), 0)).where(RetestEvent.account_key == key)).one()
    return int(row[0]), int(row[1])


def _costs(policy: dict, scenario: str) -> tuple[int, int, int]:
    base = policy["baseline_policy"]
    slip = 3 if scenario == "stress" else base["slippage_premium_cents"]
    return (slip*100, base["opening_commission_cents"]+base["fee_allowance_per_side_cents"],
            base["closing_commission_cents"]+base["fee_allowance_per_side_cents"])


def _capacity(db: Session, position: RetestPosition, policy: dict, ask: float | None) -> bool:
    if position.account_key is None:
        return True  # Opportunity evidence is explicitly NOT a cash account.
    other = db.scalars(select(RetestPosition.status).where(RetestPosition.account_key == position.account_key,
        RetestPosition.id != position.id, RetestPosition.status.in_(HELD))).all()
    slip, opening, closing = _costs(policy, position.scenario)
    settled, _ = balance(db, position.account_key)
    debit = cents(ask*100)+slip+opening if ask is not None and math.isfinite(ask) else None
    return (len(other) < policy["baseline_policy"]["max_positions"] and
            (debit is None or (debit+closing <= policy["baseline_policy"]["max_entry_cents"] and
             debit+closing <= settled-len(other)*closing)))


def _cached_quote(provider, plan: dict) -> OptionContractOut | None:
    if provider is None or not hasattr(provider, "cached_option_chain"):
        return None
    status = provider.status()
    if status.status != "healthy" or status.mode != "live" or status.provider != "tastytrade":
        return None
    contract = plan["contract"]
    rows = provider.cached_option_chain(plan["ticker"], date.fromisoformat(contract["expiration"])) or []
    return next((q for q in rows if q.option_symbol.strip().upper() == contract["option_symbol"].strip().upper()), None)


def _verified(quote, plan: dict, now: datetime, earliest: datetime, age=60) -> bool:
    if quote is None or quote.provider != "tastytrade" or quote.receipt_basis != "REST_RESPONSE_RECEIVED_V1":
        return False
    original = plan["contract"]
    if (quote.expiration.isoformat(), quote.strike, quote.right) != (original["expiration"], original["strike"], original["right"]):
        return False
    if not all(math.isfinite(n) for n in (quote.bid, quote.ask)):
        return False
    clocks = (quote.bid_timestamp, quote.ask_timestamp, quote.received_at)
    try:
        if any(t is None or not max(earliest, now-timedelta(seconds=age)) <= stamp(t) <= now for t in clocks):
            return False
    except ValueError:
        return False
    return validate_exit_quote(quote, plan["ticker"], original["option_symbol"],
                               max(earliest, now-timedelta(seconds=age)), age).actionable


def refresh_quotes(db: Session, provider, *, now: datetime) -> int:
    """After ALL baseline work; shared requests across arms, held exposure first."""
    run = db.get(RetestRun, KEY)
    if (run is None or market_session(now) != "regular" or provider is None
            or not hasattr(provider, "option_chain") or not hasattr(provider, "budget_status")
            or not hasattr(provider, "research_request_reserve")):
        return 0
    positions = list(db.scalars(select(RetestPosition).where(RetestPosition.status.in_(
        ("OPEN", "EXIT_PENDING", "WAIT_RETEST", "PENDING_ENTRY"))).order_by(RetestPosition.id)).all())
    positions.sort(key=lambda p: (p.status not in HELD, p.id))
    used = 0; seen = set()
    for position in positions:
        opportunity = db.get(RetestOpportunity, position.opportunity_id)
        if opportunity is None or opportunity.run_key != KEY:
            continue
        plan = opportunity.frozen
        if "contract" not in plan:
            continue
        pair = (plan["ticker"], date.fromisoformat(plan["contract"]["expiration"]))
        if pair in seen:
            continue
        seen.add(pair)
        remaining = provider.budget_status().get("remaining")
        # Unknown budget fails closed. One chain call may perform multiple upstream
        # requests: retain an additional 10-request buffer beyond baseline reserve.
        if remaining is None or remaining <= run.policy["baseline_policy"]["request_reserve"]+10 or used >= 2:
            break
        q = _cached_quote(provider, plan)
        if q is not None and _verified(q, plan, now, now-timedelta(seconds=30)):
            continue
        try:
            with provider.research_request_reserve(run.policy["baseline_policy"]["request_reserve"]):
                provider.option_chain(*pair)
        except (KeyError, ValueError, RuntimeError):
            pass
        used += 1
    return used


def _freeze(candidate, evaluation_at, now, capture, policy) -> dict:
    limits = session_limits(evaluation_at.astimezone(NY).date())
    if now >= limits["entry_cutoff"]:
        raise ValueError("ENTRY_CUTOFF")
    contract = candidate.contract
    assert contract is not None
    levels = (candidate.underlying_trigger, candidate.underlying_invalidation, candidate.first_underlying_target)
    if any(v is None or not math.isfinite(v) or v <= 0 for v in levels):
        raise ValueError("INVALID_LEVELS")
    plan = {"ticker": candidate.symbol, "mode": candidate.strategy_mode, "direction": candidate.direction,
        "breakout_at": evaluation_at.isoformat(), "observed_at": now.isoformat(),
        "breakout": levels[0], "stop": levels[1], "target": levels[2],
        "contract": contract.model_dump(mode="json"), "candidate": candidate.model_dump(mode="json"),
        "entry_cutoff": limits["entry_cutoff"].isoformat(), "timed_exit": limits["timed_exit_candle"].isoformat(),
        "close": limits["close"].isoformat(), "session_version": SESSION_VERSION,
        "input_evidence": capture.get(candidate.symbol, {}), "spec_hash": policy["spec_hash"]}
    if candidate.strategy_mode == "ONE_MIN_0DTE":
        evidence = capture.get(candidate.symbol, {})
        if "planning_risk" not in evidence or not evidence.get("bars"):
            raise ValueError("MISSING_EXACT_PLANNING_EVIDENCE")
        setup = FrozenSetup(ticker=candidate.symbol, direction=candidate.direction,
            breakout_at=evaluation_at, observed_at=now, breakout=levels[0], stop=levels[1], target=levels[2],
            planning_risk=evidence["planning_risk"], entry_low=candidate.entry_low,
            entry_high=candidate.entry_high, no_chase=candidate.no_chase_price,
            entry_cutoff=limits["entry_cutoff"], timed_exit=limits["timed_exit_candle"],
            contract_json=contract.model_dump_json(), completed_evidence_json=canonical(evidence),
            configuration_json=canonical(policy), strategy_version=candidate.strategy_version)
        plan["retest_setup"] = setup.to_json()
    return plan


def _skip(db, p, now, reason):
    p.status = "SKIPPED"
    p.detail = {**p.detail, "reason": reason}
    event(db, f"p:{p.id}:skip", now, "SKIP", position=p, detail={"reason": reason})


def _discover(db, run, candidates, evaluation_at, now, capture):
    day = evaluation_at.astimezone(NY).date()
    for c in candidates:  # Keep existing one-minute then Structured rank order.
        if (c.signal_status != "BUY" or c.strategy_mode not in MODES or not c.actionable
                or not is_verified_actionable_contract(c.contract)):
            continue
        if db.scalar(select(RetestOpportunity.id).where(RetestOpportunity.run_key == KEY,
                RetestOpportunity.trading_date == day, RetestOpportunity.ticker == c.symbol,
                RetestOpportunity.mode == c.strategy_mode)):
            continue
        selected = not db.scalar(select(RetestOpportunity.id).where(RetestOpportunity.run_key == KEY,
            RetestOpportunity.trading_date == day, RetestOpportunity.ticker == c.symbol))
        try:
            expected = run.policy["baseline_policy"]["strategy_versions"].get(c.strategy_mode)
            if c.strategy_version != expected or c.contract.provider != "tastytrade":
                raise ValueError("BASELINE_VERSION_OR_PROVIDER_MISMATCH")
            if (c.input_evidence.get("input_version") != run.policy["baseline_policy"]["required_input_version"]
                    or c.input_evidence.get("session_date") != day.isoformat()
                    or c.contract.right != c.direction):
                raise ValueError("BASELINE_SESSION_OR_DIRECTION_MISMATCH")
            plan = _freeze(c, evaluation_at, now, capture, run.policy)
        except (ValueError, TypeError) as exc:
            plan = {"freeze_error": str(exc), "candidate": c.model_dump(mode="json")}
        opportunity = RetestOpportunity(run_key=KEY, trading_date=day, ticker=c.symbol,
            mode=c.strategy_mode, observed_at=now, selected=selected, frozen=plan)
        db.add(opportunity); db.flush()
        event(db, f"o:{opportunity.id}:frozen", now, "OPPORTUNITY", detail={
            "opportunity_id": opportunity.id, "selected": selected, "plan": plan})
        for scenario in (*SCENARIOS, "opportunity"):
            if scenario == "opportunity" and c.strategy_mode != "ONE_MIN_0DTE":
                continue
            for arm in ARMS:
                p = RetestPosition(opportunity_id=opportunity.id,
                    account_key=None if scenario == "opportunity" else account_key(arm, scenario),
                    arm=arm, scenario=scenario, status="PENDING_ENTRY", detail={
                        "checked_through": evaluation_at.isoformat(), "created_at": now.isoformat()})
                db.add(p); db.flush()
                if "freeze_error" in plan:
                    _skip(db, p, now, plan["freeze_error"]); continue
                if not selected and scenario != "opportunity":
                    _skip(db, p, now, "SHARED_TICKER_DAY_SELECTION"); continue
                if arm == "treatment" and c.strategy_mode == "ONE_MIN_0DTE":
                    timing = start(FrozenSetup.from_json(plan["retest_setup"]))
                    p.status = "WAIT_RETEST"
                    p.detail = {**p.detail, "timing": timing.to_json()}
                    _timing_events(db, p, timing, now)
                else:
                    p.detail = {**p.detail, "requested_at": now.isoformat()}
                    event(db, f"p:{p.id}:entry-request", now, "ENTRY_REQUEST", position=p,
                          detail={"opportunity_id": opportunity.id})


def _timing_events(db, p, state, now):
    for raw in state.events:
        payload = json.loads(raw)
        kind = payload["kind"]
        event(db, f"p:{p.id}:timing:{payload['sequence']}", now, kind, position=p, detail=payload)


def _bars(provider, ticker, capture) -> list[CandleOut]:
    rows = [CandleOut.model_validate(b) for b in capture.get(ticker, {}).get("bars", [])]
    if provider is not None and hasattr(provider, "cached_candles"):
        cached = provider.cached_candles(ticker)
        if cached:
            rows = cached
    return rows


def _bar_exit(plan, p, bars, now) -> tuple[str | None, datetime | None]:
    """Chronological underlying evidence; no fabricated exit on a missing minute."""
    detail = p.detail
    cursor = datetime.fromisoformat(detail["checked_through"])
    boundary = now.replace(second=0, microsecond=0)-timedelta(minutes=1)
    rows: dict[datetime, CandleOut] = {}
    for b in bars:
        at = stamp(b.timestamp)
        if b.symbol != plan["ticker"] or b.timeframe != "1m" or not cursor < at <= boundary:
            continue
        if (at.second or at.microsecond or not all(math.isfinite(n) and n > 0 for n in (b.open,b.high,b.low,b.close))
                or not b.low <= min(b.open,b.close) <= max(b.open,b.close) <= b.high
                or (at in rows and rows[at] != b)):
            return "DATA_GAP", None
        rows[at] = b
    next_at = cursor+timedelta(minutes=1)
    while next_at <= boundary:
        if next_at >= datetime.fromisoformat(plan["close"]):
            return "DATA_GAP", None
        b = rows.get(next_at)
        if b is None:
            return "DATA_GAP", None
        p.detail = {**p.detail, "checked_through": next_at.isoformat()}
        stop = b.low <= plan["stop"] if plan["direction"] == "call" else b.high >= plan["stop"]
        target = b.high >= plan["target"] if plan["direction"] == "call" else b.low <= plan["target"]
        reason = "STOP" if stop else "TARGET" if target else "TIMED_EXIT" if next_at >= datetime.fromisoformat(plan["timed_exit"]) else None
        if reason:
            entry = p.detail.get("entry_at")
            if entry and next_at < datetime.fromisoformat(entry):
                return "AMBIGUOUS_ENTRY_BAR", None
            return reason, next_at+timedelta(minutes=1)
        next_at += timedelta(minutes=1)
    return None, None


def _unknown(db, p, now, reason):
    p.status = "UNPRICED"
    p.detail = {**p.detail, "reason": reason}
    # Every held failure implies an exit requirement; never exclude it from coverage.
    event(db, f"p:{p.id}:exit-request", now, "EXIT_REQUEST", position=p, detail={"reason": reason})
    event(db, f"p:{p.id}:unknown", now, "UNKNOWN_EXPOSURE", position=p, detail={"reason": reason})


def _advance_position(db, run, p, opportunity, provider, now, capture):
    plan = opportunity.frozen
    if p.status in ("SKIPPED", "CLOSED", "UNPRICED"):
        return
    if p.status == "UNSETTLED":
        due = p.detail.get("settles_at")
        if due and now >= datetime.fromisoformat(due):
            sale = p.detail["sale_cents"]
            event(db, f"p:{p.id}:settlement", now, "SETTLEMENT", position=p,
                  settled=sale if p.account_key else 0, unsettled=-sale if p.account_key else 0)
            p.status = "CLOSED"
        return
    close = datetime.fromisoformat(plan["close"])
    cutoff = datetime.fromisoformat(plan["entry_cutoff"])
    held = p.status in HELD
    if now >= close or (not held and now >= cutoff):
        if held: _unknown(db, p, now, "SESSION_ENDED_WITHOUT_EXIT")
        else: _skip(db, p, now, "SESSION_CUTOFF")
        return
    if provider is None:
        return  # Startup has not acquired current candles; wait for the real scan.
    bars = _bars(provider, plan["ticker"], capture)
    quote = _cached_quote(provider, plan)
    policy = run.policy["baseline_policy"]
    slip, opening, closing = _costs(run.policy, p.scenario)
    if p.status in ("WAIT_RETEST", "PENDING_ENTRY"):
        if p.arm == "treatment" and opportunity.mode == "ONE_MIN_0DTE":
            state = advance(FrozenSetup.from_json(plan["retest_setup"]), TimingState.from_json(p.detail["timing"]),
                now=now, candles=bars, quote=quote,
                capacity_available=_capacity(db, p, run.policy, quote.ask if quote else None))
            _timing_events(db, p, state, now)
            p.detail = {**p.detail, "timing": state.to_json(), "checked_through": state.checked_through.isoformat()}
            if state.requested_at:
                p.detail = {**p.detail, "requested_at": state.requested_at.isoformat()}
            if state.phase == "CANCELLED":
                _skip(db, p, now, state.reason); return
            p.status = state.phase if state.phase != "ENTRY_ELIGIBLE" else "PENDING_ENTRY"
            if state.phase != "ENTRY_ELIGIBLE":
                return
        else:
            reason, _ = _bar_exit(plan, p, bars, now)
            if reason:
                _skip(db, p, now, f"{reason}_BEFORE_ENTRY"); return
        requested = datetime.fromisoformat(p.detail["requested_at"])
        if now > requested+timedelta(seconds=policy["entry_deadline_seconds"]):
            _skip(db, p, now, "ENTRY_QUOTE_DEADLINE"); return
        if not _verified(quote, plan, now, requested+timedelta(seconds=1)):
            return
        assert quote is not None
        event(db, f"p:{p.id}:entry-quote", now, "ENTRY_QUOTE_AVAILABLE", position=p,
              detail={"quote": quote.model_dump(mode="json")})
        if quote.bid <= 0 or (quote.ask-quote.bid)/quote.ask*100 > policy["entry_max_spread_percent"]:
            _skip(db, p, now, "ENTRY_SPREAD"); return
        if not _capacity(db, p, run.policy, quote.ask):
            _skip(db, p, now, "CAPACITY_SKIP"); return
        debit = cents(quote.ask*100)+slip+opening
        p.status = "OPEN"
        # Recheck the entry-minute bar when completed, but never award a hindsight
        # stop/target touch that may predate the actual quote fill.
        p.detail = {**p.detail, "entry_at": now.isoformat(), "entry_debit_cents": debit,
            "entry_quote": quote.model_dump(mode="json"), "valuation": quote.model_dump(mode="json"),
            "checked_through": (now.replace(second=0,microsecond=0)-timedelta(minutes=1)).isoformat()}
        event(db, f"p:{p.id}:entry", now, "ENTRY", position=p,
              settled=-debit if p.account_key else 0, detail=p.detail)
        return
    if p.status == "OPEN":
        reason, end = _bar_exit(plan, p, bars, now)
        if reason:
            if end is None or now > end+timedelta(seconds=policy["exit_deadline_seconds"]):
                _unknown(db, p, now, reason); return
            p.status = "EXIT_PENDING"
            p.detail = {**p.detail, "exit_requested_at": now.isoformat(), "exit_event_at": end.isoformat(),
                        "exit_reason": reason}
            event(db, f"p:{p.id}:exit-request", now, "EXIT_REQUEST", position=p, detail=p.detail)
    if p.status == "EXIT_PENDING":
        requested = datetime.fromisoformat(p.detail["exit_requested_at"])
        if now > requested+timedelta(seconds=policy["exit_deadline_seconds"]):
            _unknown(db, p, now, "EXIT_QUOTE_DEADLINE"); return
        if _verified(quote, plan, now, requested+timedelta(seconds=1)):
            assert quote is not None
            event(db, f"p:{p.id}:exit-quote", now, "EXIT_QUOTE_AVAILABLE", position=p,
                  detail={"quote": quote.model_dump(mode="json")})
            sale = max(0, cents(quote.bid*100)-slip)
            pnl = sale-closing-p.detail["entry_debit_cents"]
            due = settlement_at(now)
            p.status = "UNSETTLED"
            p.detail = {**p.detail, "exit_at": now.isoformat(), "exit_quote": quote.model_dump(mode="json"),
                "sale_cents": sale, "closing_cost_cents": closing, "net_pnl_cents": pnl,
                "settles_at": due.isoformat() if due else None}
            event(db, f"p:{p.id}:exit", now, "EXIT", position=p,
                  settled=-closing if p.account_key else 0, unsettled=sale if p.account_key else 0,
                  realized=pnl if p.account_key else 0, detail=p.detail)
    if p.status in ("OPEN", "EXIT_PENDING") and _verified(quote, plan, now, datetime.fromisoformat(p.detail["entry_at"])):
        assert quote is not None
        p.detail = {**p.detail, "valuation": quote.model_dump(mode="json")}


def _equity(db, account, run, now) -> dict:
    settled, unsettled = balance(db, account.key)
    positions = db.scalars(select(RetestPosition).where(RetestPosition.account_key == account.key,
                                                       RetestPosition.status.in_(HELD))).all()
    slip, _, closing = _costs(run.policy, account.scenario)
    liquidation = 0; unknown = 0; evidence = []
    for p in positions:
        o = db.get(RetestOpportunity, p.opportunity_id)
        raw = p.detail.get("valuation")
        q = OptionContractOut.model_validate(raw) if raw else None
        if (p.status == "UNPRICED" or market_session(now) != "regular" or
                not _verified(q, o.frozen, now, now-timedelta(seconds=60))):
            unknown += 1
        else:
            assert q is not None
            liquidation += max(0, cents(q.bid*100)-slip)-closing
        evidence.append({"position_id": p.id, "status": p.status, "quote": raw})
    return {"cash_cents": settled+unsettled, "settled_cents": settled, "unsettled_cents": unsettled,
        "equity_cents": None if unknown else settled+unsettled+liquidation,
        "unknown": unknown, "reserved_closing_cents": len(positions)*closing, "positions": evidence}


def process(db: Session, provider=None, *, candidates=(), evaluation_at=None, capture=None,
            now: datetime | None = None) -> None:
    run = db.get(RetestRun, KEY)
    if run is None:
        return  # Crucially, startup/scanning never activates or deposits cash.
    now = stamp(now or datetime.now(timezone.utc)); capture = capture or {}
    db.execute(update(RetestRun).where(RetestRun.key == KEY).values(revision=RetestRun.revision+1))
    db.refresh(run)  # Write lock before checking state; caller commits atomically.
    if now <= utc(run.processed_at):
        return
    if evaluation_at is not None:
        evaluation_at = stamp(evaluation_at)
        if db.scalar(select(RetestObservation.id).where(RetestObservation.run_key == KEY,
                                                       RetestObservation.evaluation_at == evaluation_at)):
            return
    run.processed_at = now
    drift = configuration() != run.policy["configuration"] or code_hash() != run.policy["code_hash"]
    if drift:
        event(db, "protocol-drift", now, "PROTOCOL_DRIFT", detail={"new_entries_disabled": True})
    positions = list(db.scalars(select(RetestPosition).join(RetestOpportunity).where(
        RetestOpportunity.run_key == KEY, RetestPosition.status.in_(("WAIT_RETEST", "PENDING_ENTRY", "OPEN", "EXIT_PENDING", "UNSETTLED")))
        .order_by(RetestPosition.id)).all())
    # Exits/settlement before pending admissions, stable ordering across accounts.
    positions.sort(key=lambda p: (p.status not in (*HELD, "UNSETTLED"), p.id))
    for p in positions:
        opportunity = db.get(RetestOpportunity, p.opportunity_id)
        if drift and p.status in ("WAIT_RETEST", "PENDING_ENTRY"):
            _skip(db, p, now, "PROTOCOL_DRIFT")
        else:
            _advance_position(db, run, p, opportunity, provider, now, capture)
    if provider is None and market_session(now) == 'regular':
        db.flush()
        return  # No fabricated candle observation at a mid-session restart.
    if (not drift and evaluation_at is not None and evaluation_at >= utc(run.activated_at)
            and evaluation_at.astimezone(NY).date().isoformat() in run.policy["sessions"]
            and now.astimezone(NY).date() == evaluation_at.astimezone(NY).date()
            and now.replace(second=0, microsecond=0)-timedelta(minutes=1) == evaluation_at
            and market_session(now) == "regular"):
        _discover(db, run, candidates, evaluation_at, now, capture)
    db.flush()
    # Uncapped opportunity paths remain observable even after an account skip.
    # These labels describe underlying paths, never option fills or captured peaks.
    from types import SimpleNamespace
    raw_positions = db.scalars(select(RetestPosition).join(RetestOpportunity).where(
        RetestOpportunity.run_key == KEY, RetestPosition.scenario == "opportunity",
        RetestPosition.detail['opportunity_outcome'].as_string().is_(None),
        RetestOpportunity.frozen['freeze_error'].as_string().is_(None))).all()
    for p in raw_positions:
        if p.detail.get("opportunity_outcome"):
            continue
        opportunity = db.get(RetestOpportunity, p.opportunity_id)
        assert opportunity is not None
        plan = opportunity.frozen
        if "freeze_error" in plan:
            continue
        projection = SimpleNamespace(detail={"checked_through": p.detail.get("opportunity_cursor", plan["breakout_at"])})
        reason, at = _bar_exit(plan, projection, _bars(provider, plan["ticker"], capture), now)
        p.detail = {**p.detail, "opportunity_cursor": projection.detail["checked_through"]}
        if reason:
            outcome = {"reason": reason, "at": at.isoformat() if at else None,
                       "basis": "FROZEN_UNDERLYING_PATH_NOT_OPTION_RETURN"}
            p.detail = {**p.detail, "opportunity_outcome": outcome}
            event(db, f"p:{p.id}:opportunity-path", now, "OPPORTUNITY_PATH", position=p, detail=outcome)
    # Every observation includes liquidation equity, including explicit unknowns.
    accounts = db.scalars(select(RetestAccount).where(RetestAccount.run_key == KEY)).all()
    values = {a.key: _equity(db, a, run, now) for a in accounts}
    inputs = {}
    if evaluation_at is not None:
        opening = datetime.combine(evaluation_at.astimezone(NY).date(), datetime.min.time().replace(hour=9,minute=30), NY)
        expected = max(0, int((evaluation_at-opening).total_seconds()/60)+1)
        for symbol in run.policy["configuration"]["universe"]:
            bars = _bars(provider, symbol, capture)
            points = {stamp(b.timestamp) for b in bars if opening <= stamp(b.timestamp) <= evaluation_at
                and b.symbol == symbol and b.timeframe == '1m' and b.volume >= 0
                and all(math.isfinite(n) and n > 0 for n in (b.open,b.high,b.low,b.close))
                and b.low <= min(b.open,b.close) <= max(b.open,b.close) <= b.high}
            inputs[symbol] = (expected > 0 and all(opening+timedelta(minutes=i) in points for i in range(expected)))
    evaluation_at = evaluation_at or now.replace(second=0, microsecond=0)-timedelta(minutes=1)
    if not db.scalar(select(RetestObservation.id).where(RetestObservation.run_key == KEY,
                                                      RetestObservation.evaluation_at == evaluation_at)):
        db.add(RetestObservation(run_key=KEY, evaluation_at=evaluation_at, observed_at=now,
            detail={"accounts": values, "inputs": inputs, "protocol_drift": drift}))
    db.flush()


def main():
    import argparse
    from app.db.session import SessionLocal
    parser = argparse.ArgumentParser(description="Explicit prospective paper activation; no live orders")
    parser.add_argument("action", choices=["activate"])
    parser.add_argument("--revision", required=True)
    parser.add_argument("--confirm", required=True, choices=["ACTIVATE-PAIRED-PAPER-RESEARCH"])
    args = parser.parse_args()
    with SessionLocal.begin() as db:
        run = activate(db, revision=args.revision, now=datetime.now(timezone.utc))
        print(json.dumps({"run": run.key, "activated_at": utc(run.activated_at).isoformat(),
                          "spec_hash": run.policy["spec_hash"]}))


if __name__ == "__main__":
    main()
