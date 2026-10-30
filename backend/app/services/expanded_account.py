"""Independent ten-position forward paper account.

Versioned fork of the a99fe8e cash-account writer. The original writer is part
of the active retest experiment's frozen code fingerprint; do not refactor it
through this module. Shared read/quote helpers remain unchanged. No live orders.
Activation is explicit, after hours, and never performed by GET or startup.
"""
from datetime import datetime, timedelta, timezone
import math
import re

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (AutomatedOptionMark, ForwardPaperAccount, ForwardPaperEvent,
                           ForwardPaperPosition, SignalPerformance)
from app.services import forward_account as baseline
from app.services.forward_account import (HELD, _evidence, _equity_history, _quote,
    _record_equity_snapshot, _valuation, cents, settlement_at)
from app.services.market_calendar import NY, market_close, market_session
from app.services.option_research import utc
from app.services.execution_revision import VERSION as EXECUTION_VERSION, ExitEvidenceProvider

KEY = "tasty-capacity-ten-v1"
LABEL = "Tastytrade · ten-position paper account"
STARTING_CASH = 2000


def activate(db: Session, *, revision: str, now: datetime) -> ForwardPaperAccount:
    """One-time caller-owned transaction; no imports, resets or automatic activation."""
    now = utc(now)
    existing = db.get(ForwardPaperAccount, KEY)
    if existing is not None:
        if not db.scalar(select(ForwardPaperEvent.id).where(
                ForwardPaperEvent.account_key == KEY, ForwardPaperEvent.event_key == "funding")):
            raise ValueError("Partial activation; manual review required")
        return existing
    if market_session(now) == "regular":
        raise ValueError("Activate after market close; no mid-session cohort")
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Exact reviewed Git revision required")
    settings = get_settings()
    if not settings.paper_only or settings.market_data_provider != "tastytrade":
        raise ValueError("Explicit Tastytrade paper configuration required")
    old = db.get(ForwardPaperAccount, baseline.KEY)
    if old is None:
        raise ValueError("Existing baseline policy required")
    policy = dict(old.policy)
    if (policy.get("required_provider") != "tastytrade" or policy.get("max_positions") != 3
            or policy.get("starting_cash_cents") != 200000 or policy.get("quantity") != 1):
        raise ValueError("Baseline differs from reviewed policy")
    policy.update(version=KEY, label=LABEL, max_positions=10, starting_cash_cents=200000,
                  baseline_account=baseline.KEY, revision=revision, live_orders=False,
                  activation="EXPLICIT_AFTER_HOURS", scheduled_start=None)
    account = ForwardPaperAccount(key=KEY, activated_at=now, processed_at=now, revision=0,
        mark_watermark=db.scalar(select(func.max(AutomatedOptionMark.id))) or 0, policy=policy)
    db.add(account)
    db.flush()
    _event(db, "FUNDING", "funding", now, settled=200000,
           detail={"reason": "Independent simulated capital; no imported trades or forgiven exits",
                   "policy": policy})
    _record_equity_snapshot(db, account, now)
    return account


def _event(db: Session, kind: str, key: str, now: datetime, *, settled: int = 0,
           unsettled: int = 0, fees: int = 0, realized: int = 0, detail: dict | None = None) -> None:
    db.add(ForwardPaperEvent(account_key=KEY, event_key=key, occurred_at=now, kind=kind,
        settled_cents=settled, unsettled_cents=unsettled, fee_cents=fees,
        realized_cents=realized, detail=detail or {}))
    db.flush()


def _balance(db: Session, account_key: str = KEY) -> tuple[int, int]:
    result = db.execute(select(func.coalesce(func.sum(ForwardPaperEvent.settled_cents), 0),
        func.coalesce(func.sum(ForwardPaperEvent.unsettled_cents), 0)).where(
            ForwardPaperEvent.account_key == account_key)).one()
    return int(result[0]), int(result[1])


def refresh_account_quotes(db: Session, provider, *, now: datetime | None = None) -> int:
    """Bounded read-only feed work, before the ledger's observation clock starts.

    A resolved setup may stop requesting its chain. Prioritize held exposure,
    then pending/new entries; check reported budget before each chain refresh.
    """
    now = utc(now or datetime.now(timezone.utc))
    account = db.get(ForwardPaperAccount, KEY)
    if account is None or market_session(now) != "regular" or not hasattr(provider, "option_chain"):
        return 0
    status = provider.status()
    exit_status = ExitEvidenceProvider(provider).status()
    if exit_status.status != "healthy" or status.mode != "live":
        return 0
    position_ids = select(ForwardPaperPosition.entry_mark_id).where(
        ForwardPaperPosition.account_key == KEY, ForwardPaperPosition.status.in_(("OPEN", "PENDING_ENTRY")))
    held_ids = select(ForwardPaperPosition.entry_mark_id).where(
        ForwardPaperPosition.account_key == KEY, ForwardPaperPosition.status == "OPEN")
    marks = db.scalars(select(AutomatedOptionMark).where(
        AutomatedOptionMark.mark_type == "ENTRY", AutomatedOptionMark.trading_date == now.astimezone(NY).date(),
        or_(AutomatedOptionMark.id.in_(position_ids), AutomatedOptionMark.id > account.mark_watermark))
        .order_by(case((AutomatedOptionMark.id.in_(held_ids), 0), else_=1), AutomatedOptionMark.id)).all()
    # Older held marks precede new ones. One request can serve the same chain.
    refreshed = 0
    seen: set[tuple] = set()
    held_mark_ids = set(db.scalars(held_ids).all())
    for mark in marks:
        if status.status != 'healthy' and mark.id not in held_mark_ids:
            continue  # Candle-only failure permits held exits, not new entries.
        key = (mark.ticker, mark.expiration)
        if key in seen:
            continue
        seen.add(key)
        if hasattr(provider, "cached_option_chain") and provider.cached_option_chain(*key):
            continue
        remaining = provider.budget_status().get("remaining") if hasattr(provider, "budget_status") else None
        if (refreshed >= account.policy["max_quote_refreshes"] or
                (remaining is not None and remaining <= account.policy["request_reserve"])):
            break
        try:
            provider.option_chain(*key)
        except (KeyError, ValueError, RuntimeError):
            pass  # Missing evidence remains pending/unknown in the ledger.
        refreshed += 1
    return refreshed


def advance_account(db: Session, provider=None, *, now: datetime | None = None) -> None:
    now = utc(now or datetime.now(timezone.utc))
    account = db.get(ForwardPaperAccount, KEY)
    if account is None:
        return
    # Acquire a writer lock before reading projections; events and state commit
    # atomically. The scanner also owns a process-wide lock.
    db.execute(update(ForwardPaperAccount).where(ForwardPaperAccount.key == KEY).values(
        revision=ForwardPaperAccount.revision+1))
    db.refresh(account)
    if now < utc(account.processed_at):
        return  # A backwards clock cannot retroactively create fills or settlement.
    account.processed_at = now
    policy = account.policy
    close_fee = policy["closing_commission_cents"] + policy["fee_allowance_per_side_cents"]
    positions = list(db.scalars(select(ForwardPaperPosition).where(
        ForwardPaperPosition.account_key == KEY,
        ForwardPaperPosition.status.in_(("PENDING_ENTRY", "OPEN", "UNPRICED", "UNSETTLED")))
        .order_by(ForwardPaperPosition.id)).all())
    # Process previously accepted exposure before discovering new entries.
    for position in positions:
        detail = dict(position.detail)
        if position.status == "UNSETTLED":
            due = detail.get("settles_at")
            if due and now >= datetime.fromisoformat(due):
                sale = detail["sale_cents"]
                _event(db, "SETTLEMENT", f"{position.id}:settled", now, settled=sale, unsettled=-sale,
                       detail={"position_id": position.id, "ticker": detail["ticker"]})
                position.status = "CLOSED"
            continue
        if position.status != "OPEN":
            continue
        mark = db.get(AutomatedOptionMark, position.entry_mark_id)
        row = db.get(SignalPerformance, position.signal_id)
        assert mark is not None and row is not None
        repaired = detail.get('execution_version') == EXECUTION_VERSION
        quote_provider = ExitEvidenceProvider(provider) if repaired and provider is not None else provider
        end_day = min(mark.expiration, mark.trading_date)
        end = datetime.combine(end_day, market_close(end_day), NY)
        # Do not invent expiry/assignment or recovery fills following an outage.
        if now >= end or row.exit_reason == "DATA_GAP":
            detail["reason"] = "No verified exit before session end or underlying data gap; debit remains at risk"
            position.status = "UNPRICED"
        elif row.exit_reason != "OPEN":
            event_end = utc(row.exit_at)+timedelta(minutes=1) if row.exit_at is not None else None
            if repaired and event_end is not None and now < event_end:
                continue
            # Legacy positions retain their original deadline semantics. New
            # positions admit the decision on a completed-bar clock, then use
            # only the saved decision's 180-second later-quote deadline.
            late_event = (repaired and not detail.get('exit_requested_at') and event_end is not None
                          and now > event_end+timedelta(seconds=policy['exit_deadline_seconds']))
            legacy_late = (not repaired and row.exit_at is not None
                           and now > utc(row.exit_at)+timedelta(seconds=policy['exit_deadline_seconds']))
            if (row.exit_at is None or late_event or legacy_late
                    or utc(row.exit_at)+timedelta(minutes=1) <= datetime.fromisoformat(detail["entry_at"])):
                detail["reason"] = "Underlying exit is missing, predates entry, or its quote window was missed"
                position.status = "UNPRICED"
                _event(db, "QUOTE_GAP", f"{position.id}:gap", now,
                    detail={"position_id": position.id, "ticker": detail["ticker"], "reason": detail["reason"]})
                position.detail = detail
                continue
            if not detail.get("exit_requested_at"):
                detail["exit_requested_at"] = now.isoformat()
                detail["exit_reason"] = row.exit_reason
                if repaired:
                    detail['exit_event_completed_at'] = event_end.isoformat() if event_end else None
                _event(db, "EXIT_REQUEST", f"{position.id}:exit-request", now,
                       detail={"position_id": position.id, "ticker": detail["ticker"], "reason": row.exit_reason})
            requested = datetime.fromisoformat(detail["exit_requested_at"])
            if now > requested + timedelta(seconds=policy["exit_deadline_seconds"]):
                position.status = "UNPRICED"
                detail["reason"] = "Exit quote deadline missed; no guessed proceeds"
            else:
                quote = _quote(quote_provider, mark, now, requested+timedelta(seconds=policy["minimum_latency_seconds"]), policy)
                if quote is not None:
                    sale = max(0, cents(quote.bid*100)-policy["slippage_premium_cents"]*100)
                    due = settlement_at(now)
                    detail.update(sale_cents=sale, exit_fee_cents=close_fee, exit_at=now.isoformat(),
                        exit_quote=_evidence(quote, now),
                        net_pnl_cents=sale-close_fee-detail["entry_debit_cents"],
                        settles_at=due.isoformat() if due else None)
                    position.status = "UNSETTLED"
                    _event(db, "EXIT", f"{position.id}:exit", now, settled=-close_fee,
                        unsettled=sale, fees=close_fee, realized=detail["net_pnl_cents"],
                        detail={"position_id": position.id, **detail})
        else:
            quote = _quote(quote_provider, mark, now, datetime.fromisoformat(detail["entry_at"]), policy)
            if quote is not None:
                detail["valuation"] = _evidence(quote, now)
        if position.status == "UNPRICED":
            _event(db, "QUOTE_GAP", f"{position.id}:gap", now,
                detail={"position_id": position.id, "ticker": detail["ticker"], "reason": detail["reason"]})
        position.detail = detail
    db.flush()

    marks = list(db.scalars(select(AutomatedOptionMark).where(
        AutomatedOptionMark.id > account.mark_watermark,
        AutomatedOptionMark.mark_type == "ENTRY").order_by(AutomatedOptionMark.id)).all())
    for mark in marks:
        account.mark_watermark = mark.id
        if utc(mark.created_at) < utc(account.activated_at):
            continue
        row = db.get(SignalPerformance, mark.signal_id)
        if row is None or row.source != "LIVE":
            continue
        if not db.scalar(select(ForwardPaperEvent.id).where(
                ForwardPaperEvent.account_key == KEY, ForwardPaperEvent.event_key == f'execution:{EXECUTION_VERSION}')):
            _event(db, 'EXECUTION_BOUNDARY', f'execution:{EXECUTION_VERSION}', now,
                detail={'execution_version': EXECUTION_VERSION, 'first_mark_id': mark.id,
                        'reason': 'Prospective decision-clock exits and independent verified option quote health; cash and historical positions preserved',
                        'entry_deadline_seconds': policy['entry_deadline_seconds'],
                        'exit_deadline_seconds': policy['exit_deadline_seconds']})
        position = ForwardPaperPosition(account_key=KEY, signal_id=mark.signal_id,
            entry_mark_id=mark.id, status="PENDING_ENTRY", first_seen_at=now,
            detail={"ticker": mark.ticker, "option_symbol": mark.normalized_option_symbol,
                'execution_version': EXECUTION_VERSION,
                "strategy_mode": mark.strategy_mode, "strategy_version": row.strategy_version,
                "strategy_snapshot": row.strategy_snapshot,
                "underlying_plan": {"entry": row.entry_price, "stop": row.stop_price, "target": row.target_price},
                "entry_mark_created_at": utc(mark.created_at).isoformat()})
        db.add(position)
        positions.append(position)
    db.flush()
    settled, _ = _balance(db)
    held = sum(p.status in HELD for p in positions)
    for position in positions:
        if position.status != "PENDING_ENTRY":
            continue
        detail = dict(position.detail)
        mark = db.get(AutomatedOptionMark, position.entry_mark_id)
        row = db.get(SignalPerformance, position.signal_id)
        assert mark is not None and row is not None
        age = (now-utc(mark.created_at)).total_seconds()
        reason = None
        evidence = (row.strategy_snapshot or {}).get("input_evidence", {})
        if (mark.provider != policy["required_provider"] or mark.data_mode != "live"
                or row.strategy_version != policy["strategy_versions"].get(mark.strategy_mode)
                or evidence.get("input_version") != policy["required_input_version"]
                or evidence.get("session_date") != mark.trading_date.isoformat()):
            reason = "Outside corrected Tastytrade trial: provider, strategy version or session evidence does not match"
        elif row.exit_reason != "OPEN":
            reason = "Underlying play already resolved before a simulated entry"
        elif age < 0 or age > policy["entry_deadline_seconds"]:
            reason = "Entry deadline missed; historical or downtime signals are not backfilled"
        elif mark.mark_status != "QUOTED" or mark.contract_multiplier != 100:
            reason = "Missing verified entry evidence or unsupported contract multiplier"
        elif mark.trading_date != now.astimezone(NY).date() or market_session(now) != "regular":
            reason = "Entry is outside its trading session"
        elif held >= policy["max_positions"]:
            reason = "Concurrent position limit (includes unresolved quote gaps)"
        else:
            quote = _quote(provider, mark, now, utc(position.first_seen_at)+timedelta(
                seconds=policy["minimum_latency_seconds"]), policy)
            if quote is not None:
                spread = (quote.ask-quote.bid)/quote.ask*100
                if quote.bid <= 0 or spread > policy["entry_max_spread_percent"]:
                    reason = "Refreshed entry spread exceeds account limit"
                else:
                    premium = cents(quote.ask*100)+policy["slippage_premium_cents"]*100
                    fee = policy["opening_commission_cents"]+policy["fee_allowance_per_side_cents"]
                    debit = premium+fee
                    if debit+close_fee > policy["max_entry_cents"]:
                        reason = "Entry budget exceeded, including reserved closing fee"
                    elif debit+close_fee > settled-held*close_fee:
                        reason = "Insufficient settled buying power"
                    else:
                        detail.update(entry_at=now.isoformat(), entry_debit_cents=debit,
                            entry_premium_cents=premium, entry_fee_cents=fee,
                            entry_quote=_evidence(quote, now), valuation=_evidence(quote, now))
                        position.status = "OPEN"
                        _event(db, "ENTRY", f"{position.id}:entry", now, settled=-debit, fees=fee,
                               detail={"position_id": position.id, **detail})
                        settled -= debit
                        held += 1
        if reason:
            position.status = "SKIPPED"
            detail["reason"] = reason
            _event(db, "SKIP", f"{position.id}:skip", now,
                detail={"position_id": position.id, "ticker": detail["ticker"], "reason": reason})
        position.detail = detail
    db.flush()
    _record_equity_snapshot(db, account, now)


def account_catalog(db: Session) -> list[dict]:
    return [{"key": KEY, "label": LABEL, "archived": False},
            *baseline.account_catalog(db)[:1],
            *[a for a in baseline.account_catalog(db)[1:] if a["key"] != KEY]]


def account_summary(db: Session, *, page: int = 1, account_key: str = KEY, now: datetime | None = None) -> dict:
    now = utc(now or datetime.now(timezone.utc))
    catalog = account_catalog(db)
    if account_key != KEY:
        result = baseline.account_summary(db, page=page, account_key=account_key, now=now)
        result["accounts"] = catalog
        return result
    account = db.get(ForwardPaperAccount, account_key)
    if account is None:
        return {"status": "NOT_STARTED", "paper_only": True,
                "account_key": KEY, "accounts": catalog, "activation_required": True,
                "starting_cash_cents": cents(STARTING_CASH)}
    archived = account_key != KEY
    # Never load every event's potentially large strategy/quote JSON for polling.
    event_totals = db.execute(select(ForwardPaperEvent.occurred_at, ForwardPaperEvent.settled_cents,
        ForwardPaperEvent.unsettled_cents, ForwardPaperEvent.realized_cents, ForwardPaperEvent.fee_cents)
        .where(ForwardPaperEvent.account_key == account_key).order_by(ForwardPaperEvent.id)
        .execution_options(yield_per=500))
    active = list(db.scalars(select(ForwardPaperPosition).where(
        ForwardPaperPosition.account_key == account_key,
        ForwardPaperPosition.status.in_(("PENDING_ENTRY", "OPEN", "UNPRICED", "UNSETTLED")))
        .order_by(ForwardPaperPosition.id)).all())
    settled = unsettled = pnl = fees = 0
    daily: dict[str, dict] = {}
    count = 0
    for event in event_totals:
        count += 1
        settled += event.settled_cents
        unsettled += event.unsettled_cents
        pnl += event.realized_cents
        fees += event.fee_cents
        day = utc(event.occurred_at).astimezone(NY).date().isoformat()
        daily[day] = {"date": day, "cash_cents": settled+unsettled, "realized_cents": pnl}
    value = _valuation(active, account.policy, now, archived=archived)
    page_size = 20
    pages = max(1, math.ceil(count/page_size))
    requested_page = page
    page = max(1, min(page, pages))
    visible = db.scalars(select(ForwardPaperEvent).where(ForwardPaperEvent.account_key == account_key)
        .order_by(ForwardPaperEvent.id.desc()).offset((page-1)*page_size).limit(page_size)).all()
    trade_count = db.scalar(select(func.count()).select_from(ForwardPaperPosition).where(
        ForwardPaperPosition.account_key == account_key)) or 0
    trade_pages = max(1, math.ceil(trade_count/page_size))
    trade_page = max(1, min(requested_page, trade_pages))
    trades = db.scalars(select(ForwardPaperPosition).where(ForwardPaperPosition.account_key == account_key)
        .order_by(ForwardPaperPosition.id.desc()).offset((trade_page-1)*page_size).limit(page_size)).all()
    return {"status": "ARCHIVED" if archived else "ACTIVE", "paper_only": True, "account_key": account_key,
        'execution_boundaries': [{'at': utc(e.occurred_at).isoformat(), **e.detail} for e in db.scalars(
            select(ForwardPaperEvent).where(ForwardPaperEvent.account_key == account_key,
                ForwardPaperEvent.kind == 'EXECUTION_BOUNDARY').order_by(ForwardPaperEvent.id))],
        "accounts": catalog,
        "activated_at": utc(account.activated_at).isoformat(), "as_of": now.isoformat(), "policy": account.policy,
        "processed_at": utc(account.processed_at).isoformat(),
        "processing_stale": not archived and market_session(now) == "regular" and (now-utc(account.processed_at)).total_seconds() > 180,
        "settled_cents": settled, "unsettled_cents": unsettled,
        "available_cents": settled-value["reserved_exit_fees_cents"],
        "realized_cents": pnl, "charged_fees_cents": fees, **value,
        "equity_cents": None if value["unpriced_positions"] else settled+unsettled+value["known_liquidation_cents"],
        "equity_history": _equity_history(db, account),
        "daily": list(daily.values()),
        "positions": [{"id": p.id, "status": p.status, **p.detail} for p in active],
        "trades": [{"id": p.id, "status": p.status, **p.detail,
                    "estimated_net_proceeds_cents": _valuation([p], account.policy, now)["known_liquidation_cents"]
                    if not archived and p.status == "OPEN" and not _valuation([p], account.policy, now)["unpriced_positions"] else None,
                    "net_proceeds_cents": p.detail["sale_cents"]-p.detail.get("exit_fee_cents", 0)
                    if "sale_cents" in p.detail else None} for p in trades],
        "trade_pagination": {"page": trade_page, "pages": trade_pages, "total": trade_count},
        "events": [{"id": e.id, "kind": e.kind, "at": utc(e.occurred_at).isoformat(),
            "settled_cents": e.settled_cents, "unsettled_cents": e.unsettled_cents,
            "fee_cents": e.fee_cents, "realized_cents": e.realized_cents, "detail": e.detail} for e in visible],
        "pagination": {"page": page, "pages": pages, "total": count, "page_size": page_size}}
