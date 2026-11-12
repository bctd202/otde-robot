"""Passive price-cap opportunity review. No orders, funding, fills or requests.

Only new skips carry a defensible decision quote. Legacy skips stay missing
evidence. Alternative caps are independent opportunity filters, not portfolios.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import math

from sqlalchemy import func, select

from app.db.models import (AutomatedOptionMark, EntryCapReviewEvent, ForwardPaperAccount,
                           ForwardPaperPosition, SignalPerformance)
from app.services.cost_model import from_policy, exit_premium_cents
from app.services.execution_revision import ExitEvidenceProvider
from app.services.forward_account import _evidence, _quote
from app.services.market_calendar import NY, market_close
from app.services.option_research import utc
from app.services.result_model import exit_completed_at

KEY = 'tasty-capacity-ten-v1'
VERSION = 'entry-cap-review-v1'
CAPS = (12500, 15000)
REASON = 'Entry budget exceeded, including reserved closing fee'
LIMIT = 40
WINDOW = 5000
logger = logging.getLogger(__name__)


def _event(db, position_id, kind, now, detail):
    if db.scalar(select(EntryCapReviewEvent.id).where(
            EntryCapReviewEvent.position_id == position_id, EntryCapReviewEvent.kind == kind)):
        return
    db.add(EntryCapReviewEvent(position_id=position_id, kind=kind, at=now, detail=detail))
    db.flush()


def record_skip(db, position, quote, policy, *, now, debit, close_fee, settled, held):
    """Called only after the main writer has rejected an otherwise valid quote."""
    try:
        with db.begin_nested():
            if position.account_key != KEY or position.status != 'SKIPPED':
                return
            saved = json.loads(json.dumps(policy))
            room = settled-held*close_fee
            detail = {'version': VERSION, 'account_key': KEY, 'policy': saved,
                'ticker': quote.symbol, 'option_symbol': quote.option_symbol,
                'right': quote.right, 'strike': quote.strike, 'expiration': quote.expiration.isoformat(),
                'policy_hash': hashlib.sha256(json.dumps(saved, sort_keys=True).encode()).hexdigest(),
                'entry_decision_at': utc(position.first_seen_at).isoformat(),
                'entry_quote': _evidence(quote, now), 'entry_debit_cents': debit,
                'closing_reserve_cents': close_fee, 'all_in_cents': debit+close_fee,
                'source_cap_cents': policy['max_entry_cents'], 'cash_room_cents': room,
                'held_positions': held, 'cap_only': debit+close_fee <= room and held < policy['max_positions']}
            _event(db, position.id, 'ENTRY', now, detail)
    except Exception:
        logger.exception('Optional entry-cap receipt failed; original skip retained')


def advance(db, provider=None, *, now=None):
    """Bounded cache-only exit evidence after main work; failures are isolated."""
    now = utc(now or datetime.now(timezone.utc))
    try:
        with db.begin_nested():
            _advance(db, provider, now)
    except Exception:
        logger.exception('Optional entry-cap review failed; existing account work retained')


def _advance(db, provider, now):
    ended = select(EntryCapReviewEvent.position_id).where(EntryCapReviewEvent.kind.in_(('EXIT', 'GAP', 'NOT_ELIGIBLE')))
    entries = list(db.scalars(select(EntryCapReviewEvent).where(EntryCapReviewEvent.kind == 'ENTRY',
        EntryCapReviewEvent.position_id.not_in(ended)).order_by(EntryCapReviewEvent.id).limit(LIMIT)))
    for entry in entries:
        if now < utc(entry.at):
            continue
        detail = entry.detail
        if not detail['cap_only'] or not any(detail['source_cap_cents'] < detail['all_in_cents'] <= c for c in CAPS):
            _event(db, entry.position_id, 'NOT_ELIGIBLE', now, {'reason': 'Not eligible for either price-only scenario'})
            continue
        position = db.get(ForwardPaperPosition, entry.position_id)
        mark = db.get(AutomatedOptionMark, position.entry_mark_id)
        row = db.get(SignalPerformance, position.signal_id)
        policy = detail['policy']
        end = datetime.combine(min(mark.expiration, mark.trading_date), market_close(mark.trading_date), NY)
        reason = None
        if now >= end or row.exit_reason == 'DATA_GAP':
            reason = 'Session ended or underlying evidence missing; no assumed proceeds'
        elif row.exit_reason == 'OPEN':
            continue
        event_at = exit_completed_at(row)
        if not reason and (event_at is None or event_at <= utc(entry.at)):
            reason = 'Underlying exit missing or predates the hypothetical entry quote'
        if reason:
            _event(db, entry.position_id, 'GAP', now, {'reason': reason})
            continue
        assert event_at is not None
        if now < event_at:
            continue
        requested = db.scalar(select(EntryCapReviewEvent).where(
            EntryCapReviewEvent.position_id == entry.position_id, EntryCapReviewEvent.kind == 'EXIT_REQUEST'))
        if requested is None:
            if now > event_at+timedelta(seconds=policy['exit_deadline_seconds']):
                _event(db, entry.position_id, 'GAP', now, {'reason': 'Missed original exit decision window'})
                continue
            _event(db, entry.position_id, 'EXIT_REQUEST', now,
                   {'completed_at': event_at.isoformat(), 'exit_reason': row.exit_reason})
            continue  # Never execute against the quote used to make this decision.
        if now < utc(requested.at):
            continue
        if now > utc(requested.at)+timedelta(seconds=policy['exit_deadline_seconds']):
            _event(db, entry.position_id, 'GAP', now, {'reason': 'Later exit quote deadline missed'})
            continue
        q = _quote(ExitEvidenceProvider(provider) if provider is not None else None, mark, now,
                   utc(requested.at)+timedelta(seconds=policy['minimum_latency_seconds']), policy)
        if q is not None:
            cost = from_policy(policy)
            proceeds = exit_premium_cents(q.bid, cost, mark.contract_multiplier)-cost.closing_cost_cents
            _event(db, entry.position_id, 'EXIT', now, {'quote': _evidence(q, now),
                'net_proceeds_cents': proceeds, 'net_pnl_cents': proceeds-detail['entry_debit_cents']})


def summary(db, *, page=1):
    """Reads never initialize accounts, record gaps or fetch quotes."""
    account = db.get(ForwardPaperAccount, KEY)
    entries = list(db.scalars(select(EntryCapReviewEvent).where(EntryCapReviewEvent.kind == 'ENTRY')
        .order_by(EntryCapReviewEvent.id.desc()).limit(WINDOW)))
    ids = [e.position_id for e in entries]
    events = list(db.scalars(select(EntryCapReviewEvent).where(EntryCapReviewEvent.position_id.in_(ids),
        EntryCapReviewEvent.kind != 'ENTRY'))) if ids else []
    terminal = {(e.position_id, e.kind): e for e in events}
    recorded = select(EntryCapReviewEvent.position_id).where(EntryCapReviewEvent.kind == 'ENTRY')
    legacy = db.scalar(select(func.count()).select_from(ForwardPaperPosition).where(
        ForwardPaperPosition.account_key == KEY, ForwardPaperPosition.status == 'SKIPPED',
        ForwardPaperPosition.detail['reason'].as_string() == REASON,
        ForwardPaperPosition.id.not_in(recorded))) or 0
    comparisons = []
    for cap in CAPS:
        eligible = [e for e in entries if e.detail['cap_only']
                    and e.detail['source_cap_cents'] < e.detail['all_in_cents'] <= cap]
        priced = [terminal[e.position_id, 'EXIT'].detail['net_pnl_cents'] for e in eligible
                  if (e.position_id, 'EXIT') in terminal]
        gaps = sum((e.position_id, 'GAP') in terminal for e in eligible)
        comparisons.append({'cap_cents': cap, 'eligible': len(eligible), 'priced': len(priced),
            'positive': sum(v > 0 for v in priced), 'negative': sum(v < 0 for v in priced),
            'flat': sum(v == 0 for v in priced), 'gaps': gaps, 'pending': len(eligible)-len(priced)-gaps,
            'average_net_cents': sum(priced)/len(priced) if priced else None,
            'complete_quote_evidence': len(eligible) > 0 and len(priced) == len(eligible)})
    pages = max(1, math.ceil(len(entries)/20));page = min(max(1, page), pages)
    visible = entries[(page-1)*20:page*20]
    rows = []
    for e in visible:
        outcome = terminal.get((e.position_id, 'EXIT'));gap = terminal.get((e.position_id, 'GAP'))
        excluded = terminal.get((e.position_id, 'NOT_ELIGIBLE'))
        rows.append({'id': e.id, 'position_id': e.position_id, 'at': utc(e.at).isoformat(),
            **{key: e.detail[key] for key in ('ticker','option_symbol','right','strike','expiration')},
            'cap_only': e.detail['cap_only'], 'all_in_cents': e.detail['all_in_cents'],
            'source_cap_cents': e.detail['source_cap_cents'],
            'entry_ask': e.detail['entry_quote']['ask'], 'entry_quote': e.detail['entry_quote'],
            'status': 'PRICED' if outcome else 'GAP' if gap else 'NOT_ELIGIBLE' if excluded else 'PENDING',
            'net_pnl_cents': outcome.detail['net_pnl_cents'] if outcome else None,
            'exit_quote': outcome.detail['quote'] if outcome else None,
            'reason': gap.detail['reason'] if gap else excluded.detail['reason'] if excluded else None})
    total = db.scalar(select(func.count()).select_from(EntryCapReviewEvent).where(
        EntryCapReviewEvent.kind == 'ENTRY')) or 0
    return {'version': VERSION, 'account_key': KEY, 'research_only': True, 'limits_changed': False,
        'current_cap_cents': account.policy['max_entry_cents'] if account else None,
        'legacy_without_entry_receipt': legacy, 'recorded_skips': total,
        'window_records': len(entries), 'window_truncated': total > WINDOW,
        'cap_only_records': sum(e.detail['cap_only'] for e in entries),
        'comparisons': comparisons, 'page': page, 'pages': pages, 'rows': rows,
        'collection': 'CACHE_ONLY_NO_ADDITIONAL_REQUESTS', 'funded_accounts_created': 0,
        'basis': 'INDEPENDENT_OPPORTUNITIES_NOT_PORTFOLIO_RETURN',
        'limitation': 'Each scenario uses cash and slots at the actual rejection; extra hypothetical trades '
            'do not compete with each other for capital. Missing exits remain unknown. Older skips are not backfilled.'}
