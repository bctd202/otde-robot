"""Prospective lotto accounts, with preserved directional comparisons. No orders."""
from datetime import datetime, timedelta, timezone
import math

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.models import LotteryQuoteSnapshot, LotteryTracker, LottoTrialAccount, LottoTrialEvent, LottoTrialPosition
from app.services.forward_account import TRIAL_START, cents, settlement_at
from app.services.market_calendar import NY, market_close, market_session
from app.services.option_research import utc

RULES = ("fixed5", "trail40")
HELD = ("OPEN", "UNPRICED")
SHARED_TRIAL_START = datetime(2026, 10, 26, 13, 30, tzinfo=timezone.utc)


def key_for(right: str, rule: str) -> str:
    if right == "both":
        return f"lotto-v2-20261026-both-{rule}"
    return f"lotto-v1-20261019-{right}-{rule}"


def event(db, key, name, token, now, *, settled=0, unsettled=0, realized=0, detail=None):
    db.add(LottoTrialEvent(account_key=key, event_key=token, at=now, kind=name,
        settled=settled, unsettled=unsettled, realized=realized, detail=detail or {}))
    db.flush()


def balance(db, key):
    row = db.execute(select(func.coalesce(func.sum(LottoTrialEvent.settled), 0),
        func.coalesce(func.sum(LottoTrialEvent.unsettled), 0),
        func.coalesce(func.sum(LottoTrialEvent.realized), 0)).where(LottoTrialEvent.account_key == key)).one()
    return tuple(int(value) for value in row)


def ensure_lotto_trials(db: Session, now: datetime) -> None:
    now = utc(now)
    if now < TRIAL_START:
        return
    for right in ("call", "put", "both"):
        start = SHARED_TRIAL_START if right == "both" else TRIAL_START
        if now < start:
            continue
        for rule in RULES:
            key = key_for(right, rule)
            if db.get(LottoTrialAccount, key) is not None:
                continue
            policy = {"version": key, "right": right, "exit_rule": rule, "starting_cash_cents": 50000,
                "daily_debit_cap_cents": 10000, "max_positions": 1, "max_entry_cents": 5000,
                "entry_fee_cents": 150, "exit_fee_cents": 50, "slippage_cents": 100,
                "quote_age_seconds": 60, "entry_deadline_seconds": 120, "exit_deadline_seconds": 180,
                "target_multiple": 5, "trail_activation_multiple": 2, "trail_fraction": .40,
                "provider": "tastytrade", "input_version": "current-session-v2",
                "selection": ("Shared CALL/PUT cash; independent exit-rule account; "
                              "discovery time, score descending, spread ascending, symbol ascending; one ticker/day"
                              if right == "both" else
                              "Paired entries; score descending, spread ascending, symbol ascending; one ticker/day"),
                "scheduled_start": start.isoformat(), "live_orders": False}
            db.add(LottoTrialAccount(key=key, activated_at=now, processed_at=now, revision=0, policy=policy))
            db.flush()
            event(db, key, "FUNDING", "funding", now, settled=50000, detail={"policy": policy})
            event(db, key, "MARK", f"mark:{now.isoformat()}", now, detail={"equity_cents": 50000,
                "unpriced_positions": 0, "trading_date": now.astimezone(NY).date().isoformat()})


def fresh_point(db, tracker_id, now, *, after=None):
    point = db.scalar(select(LotteryQuoteSnapshot).where(LotteryQuoteSnapshot.tracker_id == tracker_id,
        LotteryQuoteSnapshot.received_at <= now).order_by(LotteryQuoteSnapshot.received_at.desc(),
        LotteryQuoteSnapshot.id.desc()).limit(1))
    if point is None or point.provider != "tastytrade" or point.data_mode != "live":
        return None
    stamps = (point.bid_timestamp, point.ask_timestamp, point.received_at)
    if any(stamp is None or not 0 <= (now-utc(stamp)).total_seconds() <= 60 for stamp in stamps):
        return None
    if after is not None and any(utc(stamp) < after for stamp in stamps):
        return None
    if not (math.isfinite(point.bid) and math.isfinite(point.ask) and 0 <= point.bid <= point.ask and point.ask > 0):
        return None
    return point


def quote_evidence(point):
    return {"snapshot_id": point.id, "bid": point.bid, "ask": point.ask,
            "bid_at": utc(point.bid_timestamp).isoformat(), "ask_at": utc(point.ask_timestamp).isoformat(),
            "received_at": utc(point.received_at).isoformat(), "provider": point.provider,
            "size_available": False}


def _unknown(db, account, position, detail, now, reason):
    position.status = "UNPRICED"
    detail["reason"] = reason
    event(db, account.key, "QUOTE_GAP", f"gap:{position.id}", now,
          detail={"position_id": position.id, "reason": reason})


def _advance_exits(db, account, positions, now):
    p = account.policy
    for position in positions:
        detail = dict(position.detail)
        if position.status == "UNSETTLED":
            if detail.get("settles_at") and now >= datetime.fromisoformat(detail["settles_at"]):
                event(db, account.key, "SETTLEMENT", f"settlement:{position.id}", now,
                    settled=detail["sale_cents"], unsettled=-detail["sale_cents"], detail={"position_id": position.id})
                position.status = "CLOSED"
            continue
        if position.status != "OPEN":
            continue
        day = datetime.fromisoformat(detail["entry_at"]).astimezone(NY).date()
        close = datetime.combine(day, market_close(day), NY)
        point = fresh_point(db, position.tracker_id, now, after=datetime.fromisoformat(detail["entry_at"]))
        if now >= close:
            _unknown(db, account, position, detail, now, "No verified exit before session close; original debit remains at risk")
        elif detail.get("exit_requested_at"):
            requested = datetime.fromisoformat(detail["exit_requested_at"])
            if now > requested+timedelta(seconds=p["exit_deadline_seconds"]):
                _unknown(db, account, position, detail, now, "Exit quote deadline missed; no invented sale")
            else:
                point = fresh_point(db, position.tracker_id, now, after=requested+timedelta(seconds=1))
                if point is not None:
                    # Thresholds trigger a decision, not a guaranteed barrier fill.
                    sale = max(0, cents(point.bid*100)-p["slippage_cents"])
                    net = sale-p["exit_fee_cents"]-detail["entry_debit_cents"]
                    due = settlement_at(now)
                    detail.update(exit_at=now.isoformat(), sale_cents=sale,
                        net_proceeds_cents=sale-p["exit_fee_cents"], net_pnl_cents=net,
                        exit_quote=quote_evidence(point), settles_at=due.isoformat() if due else None)
                    position.status = "UNSETTLED"
                    event(db, account.key, "EXIT", f"exit:{position.id}", now,
                        settled=-p["exit_fee_cents"], unsettled=sale, realized=net,
                        detail={"position_id": position.id, **detail})
        else:
            reason = "SESSION_END" if now >= close-timedelta(minutes=5) else None
            if point is not None:
                detail["valuation"] = quote_evidence(point)
                peak = max(detail.get("peak_bid", 0), point.bid)
                detail["peak_bid"] = peak
                entry_price = detail["entry_premium_cents"] / 10000
                if p["exit_rule"] == "fixed5" and point.bid >= entry_price*5:
                    reason = "5X_TRIGGER"
                if p["exit_rule"] == "trail40":
                    if peak >= entry_price*2:
                        detail.setdefault("armed_at", now.isoformat())
                    if detail.get("armed_at") and point.bid <= peak*.60:
                        reason = "40_PERCENT_TRAIL"
            if reason:
                detail.update(exit_requested_at=now.isoformat(), exit_reason=reason)
                event(db, account.key, "EXIT_REQUEST", f"request:{position.id}", now,
                    detail={"position_id": position.id, "reason": reason,
                            "quote": quote_evidence(point) if point else None})
        position.detail = detail
    db.flush()


def _paired_entries(db, accounts, positions, now):
    first = accounts[0]
    p = first.policy
    day = now.astimezone(NY).date()
    close = datetime.combine(day, market_close(day), NY)
    if market_session(now) != "regular":
        for account in accounts:
            for pos in positions[account.key]:
                if pos.status == "PENDING_ENTRY":
                    pos.status = "SKIPPED"
                    pos.detail = {**pos.detail, "reason": "Entry session ended"}
                    event(db, account.key, "SKIP", f"skip:{pos.id}", now, detail={"position_id": pos.id, **pos.detail})
        return
    seen = {pos.tracker_id for pos in positions[first.key]}
    rights = ("call", "put") if p["right"] == "both" else (p["right"],)
    shared = p["right"] == "both"
    trackers = db.scalars(select(LotteryTracker).where(LotteryTracker.trading_date == day,
        LotteryTracker.right.in_(rights), LotteryTracker.first_seen_at >= first.activated_at,
        LotteryTracker.first_seen_at <= now).order_by(LotteryTracker.first_seen_at,
        LotteryTracker.setup_score.desc(), LotteryTracker.option_symbol)).all()
    # Deterministic ordering within each scan wave, independent of later peaks.
    trackers = sorted(trackers, key=lambda t: (utc(t.first_seen_at), -t.setup_score,
        (t.entry_ask-t.entry_bid)/t.entry_ask if t.entry_ask else math.inf, t.option_symbol))
    for tracker in trackers:
        if tracker.id in seen:
            continue
        evidence = tracker.initial_snapshot.get("input_evidence", {})
        reason = None
        if (tracker.provider != "tastytrade" or tracker.data_mode != "live" or not tracker.actionable
                or tracker.expiration != day
                or evidence.get("input_version") != p["input_version"]
                or evidence.get("lottery_version") != f"lotto-{tracker.right}-session-v2"
                or evidence.get("session_date") != day.isoformat()):
            reason = "Not corrected-session live Tastytrade evidence"
        elif (now-utc(tracker.first_seen_at)).total_seconds() > p["entry_deadline_seconds"]:
            reason = "Discovery is too old; no catch-up entries after a restart"
        elif now >= close-timedelta(minutes=15):
            reason = "No new entries in final 15 minutes"
        elif any(pos.status in (*HELD, "PENDING_ENTRY") for rows in positions.values() for pos in rows):
            reason = ("Shared account already holds a CALL or PUT idea" if shared else
                      "Paired comparison already holds an idea in this direction")
        elif any(pos.detail.get("symbol") == tracker.symbol and pos.detail.get("date") == day.isoformat()
                 and pos.status != "SKIPPED" for pos in positions[first.key]):
            reason = "One selected contract per ticker/day"
        for account in accounts:
            pos = LottoTrialPosition(account_key=account.key, tracker_id=tracker.id,
                status="SKIPPED" if reason else "PENDING_ENTRY",
                detail={"symbol": tracker.symbol, "option_symbol": tracker.option_symbol,
                    "right": tracker.right, "date": day.isoformat(), "decision_at": now.isoformat(),
                    "discovered_at": utc(tracker.first_seen_at).isoformat(), "score": tracker.setup_score,
                    "input_evidence": evidence, "reason": reason})
            db.add(pos)
            db.flush()
            positions[account.key].append(pos)
            event(db, account.key, "SKIP" if reason else "ENTRY_REQUEST", f"decision:{pos.id}", now,
                  detail={"position_id": pos.id, **pos.detail})
    for pos in positions[first.key]:
        if pos.status != "PENDING_ENTRY":
            continue
        paired = [next(row for row in positions[account.key] if row.tracker_id == pos.tracker_id) for account in accounts]
        requested = datetime.fromisoformat(pos.detail["decision_at"])
        point = fresh_point(db, pos.tracker_id, now, after=requested+timedelta(seconds=1))
        reason = None
        if now > requested+timedelta(seconds=p["entry_deadline_seconds"]) or now >= close-timedelta(minutes=15):
            reason = "Entry deadline/session window missed"
        elif point is None:
            continue
        else:
            premium = cents(point.ask*100)+p["slippage_cents"]
            debit = premium+p["entry_fee_cents"]
            if point.bid <= 0 or (point.ask-point.bid)/point.ask*100 > 30:
                reason = "Entry spread exceeds 30% or no positive bid"
            elif debit+p["exit_fee_cents"] > p["max_entry_cents"]:
                reason = "Entry including costs exceeds $50"
            else:
                for account in accounts:
                    spent = sum(row.detail.get("entry_debit_cents", 0)+p["exit_fee_cents"]
                        for row in positions[account.key] if row.detail.get("entry_debit_cents") is not None
                        and row.detail["date"] == day.isoformat())
                    if balance(db, account.key)[0] < debit+p["exit_fee_cents"]:
                        reason = "Shared account lacks settled cash" if shared else "Paired account lacks settled cash"
                    if spent+debit+p["exit_fee_cents"] > p["daily_debit_cap_cents"]:
                        reason = "Shared CALL/PUT $100 daily all-in cap" if shared else "Paired $100 daily all-in cap"
        for account, row in zip(accounts, paired):
            detail = dict(row.detail)
            if reason:
                row.status = "SKIPPED"
                detail["reason"] = reason
                event(db, account.key, "SKIP", f"skip:{row.id}", now, detail={"position_id": row.id, **detail})
            else:
                row.status = "OPEN"
                detail.update(entry_at=now.isoformat(), entry_premium_cents=premium, entry_debit_cents=debit,
                    entry_quote=quote_evidence(point), valuation=quote_evidence(point), peak_bid=point.bid)
                event(db, account.key, "ENTRY", f"entry:{row.id}", now, settled=-debit,
                      detail={"position_id": row.id, **detail})
            row.detail = detail
    db.flush()


def liquidation_value(position, policy, now):
    quote = position.detail.get("valuation")
    if (position.status == "OPEN" and market_session(now) == "regular" and quote
            and all(0 <= (now-datetime.fromisoformat(quote[key])).total_seconds() <= 60
                    for key in ("bid_at", "ask_at", "received_at"))):
        return max(0, cents(quote["bid"]*100)-policy["slippage_cents"])-policy["exit_fee_cents"]
    return None


def equity(db, account, positions, now):
    settled, unsettled, realized = balance(db, account.key)
    value, unknown = settled+unsettled, 0
    for row in positions:
        if row.status not in HELD:
            continue
        marked = liquidation_value(row, account.policy, now)
        if marked is not None:
            value += marked
        else:
            unknown += 1
    return {"settled_cents": settled, "unsettled_cents": unsettled, "realized_cents": realized,
            "equity_cents": None if unknown else value, "unpriced_positions": unknown}


def advance_lotto_trials(db: Session, *, now: datetime | None = None) -> None:
    now = utc(now or datetime.now(timezone.utc))
    ensure_lotto_trials(db, now)
    # Preserve the original paired directional comparisons. The two new shared
    # accounts run independently: a slow exit must not reserve the other's slot.
    groups = [[key_for(right, rule) for rule in RULES] for right in ("call", "put")]
    groups += [[key_for("both", rule)] for rule in RULES]
    for keys in groups:
        loaded = [db.get(LottoTrialAccount, key) for key in keys]
        accounts = [account for account in loaded if account is not None]
        if len(accounts) != len(keys):
            continue
        for account in accounts:
            db.execute(update(LottoTrialAccount).where(LottoTrialAccount.key == account.key).values(
                revision=LottoTrialAccount.revision+1))
            db.refresh(account)
        if any(now < utc(account.processed_at) for account in accounts):
            continue
        positions = {account.key: list(db.scalars(select(LottoTrialPosition).where(
            LottoTrialPosition.account_key == account.key).order_by(LottoTrialPosition.id))) for account in accounts}
        for account in accounts:
            _advance_exits(db, account, positions[account.key], now)
        _paired_entries(db, accounts, positions, now)
        for account in accounts:
            account.processed_at = now
            if db.scalar(select(LottoTrialEvent.id).where(LottoTrialEvent.account_key == account.key,
                    LottoTrialEvent.event_key == f"mark:{now.isoformat()}")) is None:
                event(db, account.key, "MARK", f"mark:{now.isoformat()}", now,
                      detail={**equity(db, account, positions[account.key], now),
                              "trading_date": now.astimezone(NY).date().isoformat()})


def lotto_trial_summary(db: Session, key: str | None = None, page: int = 1, *, now: datetime | None = None) -> dict:
    now = utc(now or datetime.now(timezone.utc))
    keys = [key_for(right, rule) for right in ("both", "call", "put") for rule in RULES]
    if key is not None and key not in keys:
        raise ValueError("Unknown lotto paper trial")
    catalogue = [{"key": k,
                  "label": f"{'Calls + puts' if right == 'both' else right.upper()} · {'5× trigger' if rule == 'fixed5' else '40% trail after 2×'}",
                  "scope": "combined" if right == "both" else "directional"}
                 for right in ("both", "call", "put") for rule in RULES for k in [key_for(right, rule)]]
    selected_key = key or keys[0]
    start = SHARED_TRIAL_START if selected_key in keys[:2] else TRIAL_START
    account = db.get(LottoTrialAccount, selected_key)
    if account is None:
        return {"status": "SCHEDULED" if now < start else "NOT_STARTED", "paper_only": True,
                "account_key": selected_key, "accounts": catalogue, "scheduled_start": start.isoformat()}
    positions = list(db.scalars(select(LottoTrialPosition).where(LottoTrialPosition.account_key == account.key)
                                .order_by(LottoTrialPosition.id.desc())))
    pages = max(1, math.ceil(len(positions)/12))
    page = max(1, min(page, pages))
    marks = LottoTrialEvent
    ids = select(func.max(marks.id)).where(marks.account_key == account.key, marks.kind == "MARK").group_by(marks.detail["trading_date"].as_string())
    daily = list(db.scalars(select(marks).where(marks.id.in_(ids)).order_by(marks.at)))
    intraday = list(db.scalars(select(marks).where(marks.account_key == account.key, marks.kind == "MARK",
        marks.detail["trading_date"].as_string() == daily[-1].detail["trading_date"]).order_by(marks.at))) if daily else []

    def point(mark):
        value = mark.detail["equity_cents"]
        return {"at": utc(mark.at).isoformat(), "date": utc(mark.at).astimezone(NY).date().isoformat(),
                "equity_cents": value, "return_percent": None if value is None else (value-50000)/500,
                "unpriced_positions": mark.detail["unpriced_positions"]}

    return {"status": "ACTIVE", "paper_only": True, "accounts": catalogue, "account_key": account.key,
        "activated_at": utc(account.activated_at).isoformat(), "processed_at": utc(account.processed_at).isoformat(),
        "as_of": now.isoformat(), "policy": account.policy, **equity(db, account, positions, now),
        "direction_breakdown": direction_breakdown(positions),
        "equity_history": {"baseline_cents": 50000, "started_at": utc(account.activated_at).isoformat(),
            "daily": [point(m) for m in daily], "intraday": [point(m) for m in intraday], "basis": "Forward paper liquidation estimate after costs"},
        "trades": [{"id": p.id, "tracker_id": p.tracker_id, "status": p.status, **p.detail,
                    "estimated_net_proceeds_cents": liquidation_value(p, account.policy, now)}
                   for p in positions[(page-1)*12:page*12]],
        "pagination": {"page": page, "pages": pages, "total": len(positions)}}


def direction_breakdown(positions) -> list[dict]:
    """Full-account realized outcomes, not allocated balances or summed returns."""
    result = []
    for right in ("call", "put"):
        rows = [p for p in positions if p.detail.get("right") == right]
        closed = [p for p in rows if p.status in ("CLOSED", "UNSETTLED")]
        result.append({"right": right,
            "entered": sum(p.detail.get("entry_debit_cents") is not None for p in rows),
            "closed": len(closed), "open": sum(p.status == "OPEN" for p in rows),
            "unpriced": sum(p.status == "UNPRICED" for p in rows),
            "pending": sum(p.status == "PENDING_ENTRY" for p in rows),
            "skipped": sum(p.status == "SKIPPED" for p in rows),
            "realized_cents": sum(p.detail["net_pnl_cents"] for p in closed)})
    return result
