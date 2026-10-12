"""Forward-only cash simulation. No orders, historical replay, or signal edits.

The caller commits the position projection and immutable cash events together.
All monetary amounts are integer USD cents. GET summaries never create accounts.
"""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import math

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (AutomatedOptionMark, ForwardPaperAccount,
                           ForwardPaperEvent, ForwardPaperPosition, SignalPerformance)
from app.services.contracts import validate_exit_quote
from app.services.market_calendar import HOLIDAYS_BY_YEAR, NY, is_market_day, market_close, market_session
from app.services.option_research import utc

KEY = "forward-cash-v1"
HELD = ("OPEN", "UNPRICED")


def cents(dollars: float) -> int:
    return int((Decimal(str(dollars)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _event(db: Session, kind: str, key: str, now: datetime, *, settled: int = 0,
           unsettled: int = 0, fees: int = 0, realized: int = 0, detail: dict | None = None) -> None:
    db.add(ForwardPaperEvent(account_key=KEY, event_key=key, occurred_at=now, kind=kind,
        settled_cents=settled, unsettled_cents=unsettled, fee_cents=fees,
        realized_cents=realized, detail=detail or {}))
    db.flush()


def ensure_account(db: Session, now: datetime) -> ForwardPaperAccount:
    account = db.get(ForwardPaperAccount, KEY)
    if account is not None:
        return account
    starting = get_settings().paper_money_starting_cash
    if not math.isfinite(starting) or starting <= 0:
        raise ValueError("Forward starting cash must be finite and positive")
    account = ForwardPaperAccount(key=KEY, activated_at=utc(now), processed_at=utc(now), revision=0,
        mark_watermark=db.scalar(select(func.max(AutomatedOptionMark.id))) or 0,
        policy={"version": KEY, "starting_cash_cents": cents(starting), "quantity": 1,
            "max_positions": 3, "max_entry_cents": 10000,
            "opening_commission_cents": 100, "closing_commission_cents": 0,
            "fee_allowance_per_side_cents": 50, "slippage_premium_cents": 1,
            "entry_deadline_seconds": 120, "exit_deadline_seconds": 180,
            "minimum_latency_seconds": 1, "quote_age_seconds": 60,
            "entry_max_spread_percent": 20, "settlement": "NEXT_BANK_AND_MARKET_DAY_0930_ET",
            "max_quote_refreshes": 6, "request_reserve": 20,
            "exit_rule": "UNCHANGED_UNDERLYING_BASELINE", "live_orders": False})
    db.add(account)
    db.flush()
    _event(db, "FUNDING", "funding", utc(now), settled=cents(starting),
           detail={"reason": "New simulated capital; historical trades excluded", "policy": account.policy})
    return account


def settlement_at(now: datetime) -> datetime | None:
    """Conservative T+1 availability, with bank holidays excluded too.

    Unconfigured calendar years never release buying power. This is an account
    assumption, not a claim about a broker's intraday settlement posting time.
    """
    day = utc(now).astimezone(NY).date() + timedelta(days=1)
    for _ in range(14):
        if day.year not in HOLIDAYS_BY_YEAR:
            return None
        # Columbus Day, observed Veterans Day, and observed New Year's Day.
        columbus = day.month == 10 and day.weekday() == 0 and 8 <= day.day <= 14
        extra = set()
        for holiday in (date(day.year, 11, 11), date(day.year, 1, 1), date(day.year+1, 1, 1)):
            extra.add(holiday + timedelta(days=-1 if holiday.weekday() == 5 else
                                         1 if holiday.weekday() == 6 else 0))
        if is_market_day(day) and not columbus and day not in extra:
            return datetime.combine(day, time(9, 30), NY).astimezone(timezone.utc)
        day += timedelta(days=1)
    return None


def _quote(provider, mark: AutomatedOptionMark, now: datetime, earliest: datetime, policy: dict):
    if provider is None or not hasattr(provider, "cached_option_chain"):
        return None
    status = provider.status()
    if status.status != "healthy" or status.mode != "live" or market_session(now) != "regular":
        return None
    try:
        chain = provider.cached_option_chain(mark.ticker, mark.expiration) or []
    except (KeyError, ValueError, RuntimeError):
        return None
    for quote in chain:
        decision = validate_exit_quote(quote, mark.ticker, mark.normalized_option_symbol,
            max(earliest, now-timedelta(seconds=policy["quote_age_seconds"])), policy["quote_age_seconds"])
        if (decision.actionable and math.isfinite(quote.bid) and math.isfinite(quote.ask)
                and quote.bid_timestamp is not None and quote.ask_timestamp is not None
                and max(utc(quote.bid_timestamp), utc(quote.ask_timestamp)) <= now
                and quote.expiration == mark.expiration and quote.strike == mark.strike
                and quote.right.lower() == mark.right.lower()):
            return quote
    return None


def _evidence(quote, now: datetime) -> dict:
    return {"observed_at": now.isoformat(), "bid": quote.bid, "ask": quote.ask,
        "bid_at": utc(quote.bid_timestamp).isoformat(), "ask_at": utc(quote.ask_timestamp).isoformat(),
        "provider": quote.provider, "data_mode": quote.data_mode, "option_symbol": quote.option_symbol}


def _balance(db: Session) -> tuple[int, int]:
    result = db.execute(select(func.coalesce(func.sum(ForwardPaperEvent.settled_cents), 0),
        func.coalesce(func.sum(ForwardPaperEvent.unsettled_cents), 0)).where(
            ForwardPaperEvent.account_key == KEY)).one()
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
    if status.status != "healthy" or status.mode != "live":
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
    for mark in marks:
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
    account = ensure_account(db, now)
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
        end_day = min(mark.expiration, mark.trading_date)
        end = datetime.combine(end_day, market_close(end_day), NY)
        # Do not invent expiry/assignment or recovery fills following an outage.
        if now >= end or row.exit_reason == "DATA_GAP":
            detail["reason"] = "No verified exit before session end or underlying data gap; debit remains at risk"
            position.status = "UNPRICED"
        elif row.exit_reason != "OPEN":
            if (row.exit_at is None or now > utc(row.exit_at)+timedelta(seconds=policy["exit_deadline_seconds"])
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
                _event(db, "EXIT_REQUEST", f"{position.id}:exit-request", now,
                       detail={"position_id": position.id, "ticker": detail["ticker"], "reason": row.exit_reason})
            requested = datetime.fromisoformat(detail["exit_requested_at"])
            if now > requested + timedelta(seconds=policy["exit_deadline_seconds"]):
                position.status = "UNPRICED"
                detail["reason"] = "Exit quote deadline missed; no guessed proceeds"
            else:
                quote = _quote(provider, mark, now, requested+timedelta(seconds=policy["minimum_latency_seconds"]), policy)
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
            quote = _quote(provider, mark, now, datetime.fromisoformat(detail["entry_at"]), policy)
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
        position = ForwardPaperPosition(account_key=KEY, signal_id=mark.signal_id,
            entry_mark_id=mark.id, status="PENDING_ENTRY", first_seen_at=now,
            detail={"ticker": mark.ticker, "option_symbol": mark.normalized_option_symbol,
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
        if row.exit_reason != "OPEN":
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


def account_summary(db: Session, *, page: int = 1, now: datetime | None = None) -> dict:
    now = utc(now or datetime.now(timezone.utc))
    account = db.get(ForwardPaperAccount, KEY)
    if account is None:
        return {"status": "NOT_STARTED", "paper_only": True}
    # Never load every event's potentially large strategy/quote JSON for polling.
    event_totals = db.execute(select(ForwardPaperEvent.occurred_at, ForwardPaperEvent.settled_cents,
        ForwardPaperEvent.unsettled_cents, ForwardPaperEvent.realized_cents, ForwardPaperEvent.fee_cents)
        .where(ForwardPaperEvent.account_key == KEY).order_by(ForwardPaperEvent.id)
        .execution_options(yield_per=500))
    active = list(db.scalars(select(ForwardPaperPosition).where(
        ForwardPaperPosition.account_key == KEY,
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
    close_fee = account.policy["closing_commission_cents"]+account.policy["fee_allowance_per_side_cents"]
    unknown = unknown_debit = known_value = reserve = open_fees = 0
    for position in active:
        if position.status not in HELD:
            continue
        reserve += close_fee
        open_fees += position.detail["entry_fee_cents"]
        valuation = position.detail.get("valuation")
        if (position.status == "OPEN" and valuation and market_session(now) == "regular"
                and all(0 <= (now-datetime.fromisoformat(valuation[key])).total_seconds()
                        <= account.policy["quote_age_seconds"] for key in ("bid_at", "ask_at"))):
            known_value += max(0, cents(valuation["bid"]*100)-account.policy["slippage_premium_cents"]*100)-close_fee
        else:
            unknown += 1
            unknown_debit += position.detail["entry_debit_cents"]
    page_size = 20
    pages = max(1, math.ceil(count/page_size))
    page = max(1, min(page, pages))
    visible = db.scalars(select(ForwardPaperEvent).where(ForwardPaperEvent.account_key == KEY)
        .order_by(ForwardPaperEvent.id.desc()).offset((page-1)*page_size).limit(page_size)).all()
    return {"status": "ACTIVE", "paper_only": True, "account_key": KEY,
        "activated_at": utc(account.activated_at).isoformat(), "as_of": now.isoformat(), "policy": account.policy,
        "processed_at": utc(account.processed_at).isoformat(),
        "processing_stale": market_session(now) == "regular" and (now-utc(account.processed_at)).total_seconds() > 180,
        "settled_cents": settled, "unsettled_cents": unsettled,
        "available_cents": settled-reserve, "reserved_exit_fees_cents": reserve,
        "realized_cents": pnl, "charged_fees_cents": fees, "open_entry_fees_cents": open_fees,
        "known_liquidation_cents": known_value, "unpriced_positions": unknown,
        "unpriced_debit_cents": unknown_debit,
        "equity_cents": None if unknown else settled+unsettled+known_value,
        "daily": list(daily.values()),
        "positions": [{"id": p.id, "status": p.status, **p.detail} for p in active],
        "events": [{"id": e.id, "kind": e.kind, "at": utc(e.occurred_at).isoformat(),
            "settled_cents": e.settled_cents, "unsettled_cents": e.unsettled_cents,
            "fee_cents": e.fee_cents, "realized_cents": e.realized_cents, "detail": e.detail} for e in visible],
        "pagination": {"page": page, "pages": pages, "total": count, "page_size": page_size}}
