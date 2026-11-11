"""Isolated, explicitly activated two-leg paper research. Cache-only; no orders."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from types import SimpleNamespace

from sqlalchemy import func, or_, select, update

from app.core.config import get_settings
from app.db.models import (AutomatedOptionMark, DebitSpreadAccount, DebitSpreadEvent,
    DebitSpreadPosition, DebitSpreadSnapshot, ForwardPaperEvent, ForwardPaperPosition, SignalPerformance)
from app.services.cost_model import CostPolicy, cents, from_policy
from app.services.debit_spread_math import entry_debit, liquidation, select_hedge, theoretical
from app.services.forward_account import _evidence, _quote, settlement_at
from app.services.market_calendar import NY, market_close, market_session
from app.services.option_research import utc
from app.services.performance import automated_origin
from app.services.result_model import entry_evidence_current, exit_completed_at
from app.services.session_candles import INPUT_VERSION

KEY = 'debit-vertical-v1'
BASELINE = 'tasty-capacity-ten-v1'
HELD = ('OPEN', 'EXIT_PENDING', 'UNPRICED', 'EXPIRED_UNRESOLVED', 'ASSIGNED_UNMODELLED')
LIMIT = 40


def policy(revision):
    return {'version': KEY, 'label': 'Debit spreads · independent paper account',
        'starting_cash_cents': 200000, 'max_positions': 10, 'max_entry_cents': 25000,
        'max_daily_debit_cents': None, 'quantity': 1, 'contract_multiplier': 100,
        'required_provider': 'tastytrade', 'required_input_version': INPUT_VERSION,
        'strategy_versions': {'ONE_MIN_0DTE': 'parlay-v1-session-v2',
                             'STRUCTURED_INTRADAY': 'structured-intraday-v1-session-v2'},
        **CostPolicy().as_dict(), 'entry_deadline_seconds': 120, 'exit_deadline_seconds': 180,
        'minimum_latency_seconds': 1, 'quote_age_seconds': 60, 'alignment_seconds': 2,
        'entry_max_spread_percent': 20, 'baseline_account': BASELINE, 'revision': revision,
        'collection': 'CACHE_ONLY_NO_ADDITIONAL_REQUESTS', 'live_orders': False,
        'entry_model': 'ALL_OR_NONE_PAPER_PACKAGE_NOT_BROKER_FILL',
        'exit_rule': 'UNCHANGED_UNDERLYING_COMPLETED_EVENT', 'settlement': 'NEXT_BANK_AND_MARKET_DAY_0930_ET',
        'short_selection': 'FORMAL_TARGET_INEQUALITIES_NO_SUBSTITUTION',
        'unknown_liability_policy': 'BLOCK_NEW_ENTRIES_UNTIL_REVIEW',
        'code_hash': hashlib.sha256(b''.join((Path(__file__).parent / name).read_bytes()
            for name in ('debit_spread_account.py', 'debit_spread_math.py'))).hexdigest()}


def event(db, kind, key, now, *, settled=0, unsettled=0, realized=0, detail=None):
    if db.scalar(select(DebitSpreadEvent.id).where(DebitSpreadEvent.account_key == KEY,
                                                 DebitSpreadEvent.event_key == key)):
        return
    db.add(DebitSpreadEvent(account_key=KEY, event_key=key, at=now, kind=kind,
        settled=settled, unsettled=unsettled, realized=realized, detail=detail or {}))
    db.flush()


def balance(db):
    values = db.execute(select(func.coalesce(func.sum(DebitSpreadEvent.settled), 0),
        func.coalesce(func.sum(DebitSpreadEvent.unsettled), 0),
        func.coalesce(func.sum(DebitSpreadEvent.realized), 0)).where(DebitSpreadEvent.account_key == KEY)).one()
    return tuple(int(v) for v in values)


def activate(db, *, revision: str, now: datetime):
    now = utc(now)
    settings = get_settings()
    if not settings.debit_spread_enabled or not settings.paper_only or settings.market_data_provider != 'tastytrade':
        raise ValueError('Separate explicit enabled Tastytrade paper configuration required')
    if market_session(now) == 'regular' or not re.fullmatch('[a-f0-9]{40}', revision):
        raise ValueError('After-hours activation and exact reviewed revision required')
    old = db.get(DebitSpreadAccount, KEY)
    if old is not None:
        if not db.scalar(select(DebitSpreadEvent.id).where(DebitSpreadEvent.account_key == KEY,
                                                         DebitSpreadEvent.event_key == 'funding')):
            raise ValueError('Partial activation requires review')
        return old
    account = DebitSpreadAccount(key=KEY, activated_at=now, processed_at=now, revision=0,
        watermark=db.scalar(select(func.max(AutomatedOptionMark.id))) or 0, policy=policy(revision))
    db.add(account); db.flush()
    event(db, 'FUNDING', 'funding', now, settled=200000, detail={'policy': account.policy})
    _snapshot(db, account, [], now)
    return account


def _chain(provider, ticker, expiration):
    if provider is None or not hasattr(provider, 'cached_option_chain'):
        return []
    # The supported API does not initiate requests or refresh the cache.
    return provider.cached_option_chain(ticker, expiration) or []


def _listed(provider, ticker, expiration, now):
    """Read existing Tastytrade instrument metadata; never fetch a chain/listing.

    Quotes alone cannot prove that a missing nearer listed strike does not exist.
    This deliberately small adapter fails closed if the provider cache changes.
    """
    source = getattr(provider, 'provider', provider)
    saved = getattr(source, '_instrument_cache', {}).get(ticker)
    if not saved or not 0 <= (now-utc(saved[0])).total_seconds() <= 6*3600:
        return []
    output = []
    for raw in saved[1]:
        try:
            if raw['expiration-date'] != expiration.isoformat() or not raw.get('active', True):
                continue
            right = {'C': 'call', 'P': 'put'}[raw['option-type']]
            output.append(SimpleNamespace(symbol=ticker, expiration=expiration,
                option_symbol=re.sub(r'\s+', '', raw['symbol']).upper(),
                right=right, strike=float(raw['strike-price'])))
        except (KeyError, TypeError, ValueError):
            return []
    return output


def _identity(q):
    return {'ticker': q.symbol, 'expiration': q.expiration.isoformat(), 'strike': q.strike,
            'right': q.right, 'normalized_option_symbol': q.option_symbol}


def _pair(provider, position, now, earliest, rules, *, entry=False):
    detail = position.detail
    chain = _chain(provider, detail['ticker'], datetime.fromisoformat(detail['expiration']).date())
    if not chain:
        return None
    cache = SimpleNamespace(status=provider.status, cached_option_chain=lambda *_: chain)
    quotes = []
    for side in ('long', 'short'):
        leg = dict(detail[side]);leg['expiration'] = datetime.fromisoformat(leg['expiration']).date()
        q = _quote(cache, AutomatedOptionMark(**leg), now, earliest, rules)
        if q is None:
            return None
        if entry and (q.bid <= 0 or (q.ask-q.bid)/q.ask*100 > rules['entry_max_spread_percent']):
            return None
        quotes.append(q)
    times = [utc(t) for q in quotes for t in (q.bid_timestamp, q.ask_timestamp, q.received_at)]
    if (max(times)-min(times)).total_seconds() > rules['alignment_seconds']:
        return None
    return quotes


def _state(db, p, status, reason, now, *, listing=None):
    p.status = status;p.detail = {**p.detail, 'reason': reason}
    event(db, status, f'{p.id}:{status}', now, detail={'position_id': p.id, 'reason': reason, **({'listing_evidence': listing} if listing else {})})


def _discover(db, account, provider, now, positions):
    marks = list(db.scalars(select(AutomatedOptionMark).where(AutomatedOptionMark.mark_type == 'ENTRY',
        AutomatedOptionMark.id > account.watermark).order_by(AutomatedOptionMark.id).limit(LIMIT)))
    seen = {(p.detail['ticker'], p.detail['trading_date']) for p in positions}
    rules = account.policy
    for mark in marks:
        account.watermark = mark.id
        row = db.get(SignalPerformance, mark.signal_id)
        if db.scalar(select(DebitSpreadPosition.id).where(DebitSpreadPosition.account_key == KEY,
                                                        DebitSpreadPosition.signal_id == mark.signal_id)):
            continue
        if row is None or utc(mark.created_at) < utc(account.activated_at) or utc(row.triggered_at) < utc(account.activated_at):
            continue
        if row.source != 'LIVE' or row.backend_status != 'BUY' or not automated_origin(row):
            continue
        detail = {'ticker': row.ticker, 'trading_date': row.trading_date.isoformat(),
            'mode': row.strategy_mode, 'expiration': mark.expiration.isoformat(),
            'strategy_version': row.strategy_version, 'input_evidence': (row.strategy_snapshot or {}).get('input_evidence', {}),
            'underlying_plan': {'stop': row.stop_price, 'target': row.target_price},
            'original_entry_event_at': utc(mark.created_at).isoformat(), 'long': {}, 'short': {}}
        p = DebitSpreadPosition(account_key=KEY, signal_id=row.signal_id, trading_date=row.trading_date, status='PENDING_ENTRY',
                                decision_at=now, detail=detail)
        db.add(p);db.flush()
        reason = None
        listing = None
        evidence = detail['input_evidence']
        if (row.ticker, row.trading_date.isoformat()) in seen:
            reason = 'FIRST_TICKER_DAY_ALREADY_RECORDED'
        seen.add((row.ticker, row.trading_date.isoformat()))
        if not reason and (mark.provider != rules['required_provider'] or mark.data_mode != 'live'
                or mark.verification_status != 'verified' or mark.ticker != row.ticker
                or mark.strategy_mode != row.strategy_mode or mark.trading_date != row.trading_date
                or mark.right != row.direction.lower() or mark.expiration < row.trading_date
                or mark.mark_status != 'QUOTED' or mark.contract_multiplier != 100
                or row.strategy_version != rules['strategy_versions'].get(row.strategy_mode)
                or evidence.get('input_version') != rules['required_input_version']
                or evidence.get('session_date') != row.trading_date.isoformat()):
            reason = 'OUTSIDE_FROZEN_INPUT_POLICY'
        if not reason and (row.trading_date != now.astimezone(NY).date() or market_session(now) != 'regular'
                or row.exit_reason != 'OPEN' or not 0 <= (now-utc(mark.created_at)).total_seconds() <= 120):
            reason = 'ENTRY_SESSION_OR_DEADLINE_MISSED'
        if not reason:
            chain = _listed(provider, row.ticker, mark.expiration, now)
            source = getattr(provider, 'provider', provider)
            saved = getattr(source, '_instrument_cache', {}).get(row.ticker)
            listed = [_identity(q) for q in chain]
            listing = {
                'basis': 'CACHED_LISTING_SNAPSHOT_NOT_EXHAUSTIVE_MARKET_CLAIM',
                'cached_at': utc(saved[0]).isoformat() if saved else None,
                'instruments': listed,
                'sha256': hashlib.sha256(json.dumps(listed, sort_keys=True).encode()).hexdigest()}
            p.detail = {**p.detail, 'listing_evidence': {k: v for k, v in listing.items() if k != 'instruments'}}
            long = next((q for q in chain if q.option_symbol == mark.normalized_option_symbol
                and q.expiration == mark.expiration and q.strike == mark.strike and q.right == mark.right
                and q.symbol == row.ticker), None)
            short = select_hedge(long, row.target_price, chain) if long else None
            if short is None:
                reason = 'EXACT_PAIR_NOT_IN_CACHED_LISTINGS'
            else:
                p.detail = {**p.detail, 'long': _identity(long), 'short': _identity(short)}
        if not reason and sum(x.status in (*HELD, 'PENDING_ENTRY') for x in positions) >= rules['max_positions']:
            reason = 'CAPACITY_SKIP'
        if reason:
            _state(db, p, 'SKIPPED', reason, now, listing=listing)
        else:
            event(db, 'ENTRY_REQUEST', f'{p.id}:request', now,
                  detail={'position_id': p.id, **p.detail, 'listing_evidence': listing})
        positions.append(p)


def advance(db, provider=None, *, now=None):
    if not get_settings().debit_spread_enabled:
        return
    account = db.get(DebitSpreadAccount, KEY)
    if account is None:
        return  # Settings and startup cannot create or fund accounts.
    now = utc(now or datetime.now(timezone.utc))
    if now <= utc(account.processed_at):
        return
    db.execute(update(DebitSpreadAccount).where(DebitSpreadAccount.key == KEY)
               .values(revision=DebitSpreadAccount.revision+1))
    account.processed_at = now
    rules = account.policy;cost = from_policy(rules)
    positions = list(db.scalars(select(DebitSpreadPosition).where(DebitSpreadPosition.account_key == KEY,
        or_(DebitSpreadPosition.status.in_((*HELD, 'PENDING_ENTRY', 'UNSETTLED')),
            DebitSpreadPosition.trading_date == now.astimezone(NY).date()))
        .order_by(DebitSpreadPosition.id)))
    # Existing financial obligations precede admissions.
    for p in positions:
        d = dict(p.detail)
        if p.status == 'UNSETTLED':
            if d.get('settles_at') and now >= utc(datetime.fromisoformat(d['settles_at'])):
                amount = d['exit_credit_cents']
                event(db, 'SETTLEMENT', f'{p.id}:settle', now, settled=amount, unsettled=-amount)
                p.status = 'CLOSED'
            continue
        if p.status not in ('OPEN', 'EXIT_PENDING', 'UNPRICED'):
            continue
        row = db.get(SignalPerformance, p.signal_id)
        expiry = datetime.fromisoformat(d['expiration']).date()
        end = datetime.combine(expiry, market_close(expiry), NY)
        if now >= end:
            _state(db, p, 'EXPIRED_UNRESOLVED', 'EXPIRY_NOT_A_SALE_OR_ASSIGNMENT_RECEIPT', now)
            continue
        if p.status == 'UNPRICED':
            continue
        if row is None or row.exit_reason == 'DATA_GAP':
            _state(db, p, 'UNPRICED', 'UNDERLYING_EXIT_UNKNOWN', now)
            continue
        if row.exit_reason != 'OPEN' and p.status == 'OPEN':
            completed = exit_completed_at(row)
            if completed is None or completed <= utc(datetime.fromisoformat(d['entry_at'])):
                _state(db, p, 'UNPRICED', 'EXIT_MISSING_OR_PREDATES_ENTRY', now)
                continue
            if now < completed:
                continue
            if now > completed+timedelta(seconds=rules['exit_deadline_seconds']):
                _state(db, p, 'UNPRICED', 'UNDERLYING_EVENT_OBSERVED_TOO_LATE', now)
                continue
            p.status = 'EXIT_PENDING';d['exit_requested_at'] = now.isoformat();p.detail = d
            event(db, 'EXIT_REQUEST', f'{p.id}:exit-request', now, detail={'position_id': p.id, 'event_at': completed.isoformat()})
        if p.status == 'EXIT_PENDING':
            request = utc(datetime.fromisoformat(d['exit_requested_at']))
            if now > request+timedelta(seconds=rules['exit_deadline_seconds']):
                _state(db, p, 'UNPRICED', 'PAIRED_EXIT_QUOTE_DEADLINE', now)
                continue
            pair = _pair(provider, p, now, request+timedelta(seconds=1), rules)
            if pair:
                event(db, 'EXIT_QUOTE_AVAILABLE', f'{p.id}:exit-quotes', now,
                      detail={'position_id': p.id, 'quotes': [_evidence(q, now) for q in pair]})
                long, short = pair
                proceeds = liquidation(long.bid, short.ask, cost)
                settles = settlement_at(now) if proceeds > 0 else None
                p.detail = {**d, 'exit_at': now.isoformat(), 'exit_credit_cents': proceeds,
                    'net_pnl_cents': proceeds-d['entry_debit_cents'],
                    'settles_at': settles.isoformat() if settles else None,
                    'exit_quotes': [_evidence(q, now) for q in pair]}
                p.status = 'UNSETTLED' if proceeds > 0 else 'CLOSED'
                event(db, 'EXIT', f'{p.id}:exit', now, settled=min(0, proceeds), unsettled=max(0, proceeds),
                      realized=proceeds-d['entry_debit_cents'], detail={'position_id': p.id, **p.detail})
                continue
        pair = _pair(provider, p, now, utc(datetime.fromisoformat(d['entry_at'])), rules)
        if pair:
            p.detail = {**p.detail, 'valuation': {'at': now.isoformat(),
                'credit_cents': liquidation(pair[0].bid, pair[1].ask, cost),
                'quotes': [_evidence(q, now) for q in pair]}}
    _discover(db, account, provider, now, positions)
    for p in positions:
        if p.status != 'PENDING_ENTRY':
            continue
        row = db.get(SignalPerformance, p.signal_id)
        age = (now-utc(p.decision_at)).total_seconds()
        original = utc(datetime.fromisoformat(p.detail['original_entry_event_at']))
        if (row is None or row.exit_reason != 'OPEN' or market_session(now) != 'regular'
                or row.trading_date != now.astimezone(NY).date() or age > 120 or (now-original).total_seconds() > 120):
            _state(db, p, 'SKIPPED', 'ENTRY_INVALIDATED_OR_DEADLINE', now)
            continue
        if not entry_evidence_current(row, now):
            continue
        pair = _pair(provider, p, now, utc(p.decision_at)+timedelta(seconds=1), rules, entry=True)
        if pair is None:
            continue
        event(db, 'ENTRY_QUOTE_AVAILABLE', f'{p.id}:entry-quotes', now,
              detail={'position_id': p.id, 'quotes': [_evidence(q, now) for q in pair]})
        long, short = pair;debit = entry_debit(long.ask, short.bid, cost)
        width = cents(abs(long.strike-short.strike)*100)
        premium = debit-2*cost.opening_cost_cents
        occupied = [x for x in positions if x.status in HELD]
        settled, _, _ = balance(db)
        reserve = len(occupied)*2*cost.closing_cost_cents
        reason = None
        if not 0 < premium < width:
            reason = 'INVALID_DEBIT_OR_WIDTH'
        elif debit+2*cost.closing_cost_cents > rules['max_entry_cents']:
            reason = 'ALL_IN_ENTRY_LIMIT'
        elif _value(positions, rules, now)[1]:
            reason = 'UNKNOWN_SHORT_LEG_LIABILITY'
        elif debit+2*cost.closing_cost_cents > settled-reserve:
            reason = 'INSUFFICIENT_SETTLED_CASH'
        elif len(occupied) >= rules['max_positions']:
            reason = 'CAPACITY_SKIP'
        if reason:
            _state(db, p, 'SKIPPED', reason, now)
            continue
        p.status = 'OPEN'
        p.detail = {**p.detail, 'entry_at': now.isoformat(), 'entry_debit_cents': debit,
            'entry_quotes': [_evidence(q, now) for q in pair], 'theoretical': theoretical(long, short, premium, cost),
            'valuation': {'at': now.isoformat(), 'credit_cents': liquidation(long.bid, short.ask, cost),
                          'quotes': [_evidence(q, now) for q in pair]}}
        event(db, 'ENTRY', f'{p.id}:entry', now, settled=-debit, detail={'position_id': p.id, **p.detail})
    db.flush()
    _snapshot(db, account, positions, now)


def _value(positions, rules, now):
    credits = 0;unknown = 0
    for p in positions:
        if p.status not in HELD:
            continue
        v = p.detail.get('valuation')
        if (p.status in ('UNPRICED', 'EXPIRED_UNRESOLVED', 'ASSIGNED_UNMODELLED') or not v
                or not 0 <= (now-utc(datetime.fromisoformat(v['at']))).total_seconds() <= rules['quote_age_seconds']):
            unknown += 1
        else:
            # Source quotes also age; a fresh UI/read time never refreshes evidence.
            stamps = [utc(datetime.fromisoformat(q[k])) for q in v.get('quotes', [])
                      for k in ('bid_at', 'ask_at', 'received_at')]
            if len(stamps) != 6 or any(not 0 <= (now-t).total_seconds() <= rules['quote_age_seconds'] for t in stamps):
                unknown += 1
            else:
                credits += v['credit_cents']
    return credits, unknown


def _snapshot(db, account, positions, now):
    if db.scalar(select(DebitSpreadSnapshot.id).where(DebitSpreadSnapshot.account_key == KEY,
                                                     DebitSpreadSnapshot.at == now)):
        return
    settled, unsettled, _ = balance(db)
    credits, unknown = _value(positions, account.policy, now)
    db.add(DebitSpreadSnapshot(account_key=KEY, at=now, trading_date=now.astimezone(NY).date(), cash=settled+unsettled,
                              equity=None if unknown else settled+unsettled+credits, unknown=unknown))
    db.flush()


def summary(db, *, page=1, now=None):
    now = utc(now or datetime.now(timezone.utc))
    account = db.get(DebitSpreadAccount, KEY)
    common = {'account_key': KEY, 'enabled': get_settings().debit_spread_enabled,
              'paper_only': True, 'baseline_account': BASELINE, 'starting_cash_cents': 200000}
    if account is None:
        return {**common, 'status': 'NOT_ACTIVATED', 'activation_required': True}
    counts = dict(db.execute(select(DebitSpreadPosition.status, func.count()).where(
        DebitSpreadPosition.account_key == KEY).group_by(DebitSpreadPosition.status)).all())
    total = sum(counts.values())
    positions = list(db.scalars(select(DebitSpreadPosition).where(DebitSpreadPosition.account_key == KEY,
                                                               DebitSpreadPosition.status.in_(HELD))))
    settled, unsettled, realized = balance(db)
    credits, unknown = _value(positions, account.policy, now)
    held = [p for p in positions if p.status in HELD]
    costs = from_policy(account.policy)
    available = None if unknown or settled < 0 else max(0, settled-len(held)*2*costs.closing_cost_cents)
    daily_ids = select(func.max(DebitSpreadSnapshot.id)).where(DebitSpreadSnapshot.account_key == KEY).group_by(
        DebitSpreadSnapshot.trading_date)
    latest_day = db.scalar(select(func.max(DebitSpreadSnapshot.trading_date)).where(DebitSpreadSnapshot.account_key == KEY))
    snaps = list(db.scalars(select(DebitSpreadSnapshot).where(DebitSpreadSnapshot.account_key == KEY,
        or_(DebitSpreadSnapshot.id.in_(daily_ids), DebitSpreadSnapshot.trading_date == latest_day))
        .order_by(DebitSpreadSnapshot.at)))
    paired_rows = [SimpleNamespace(id=r.id, signal_id=r.signal_id, status=r.status,
                                  detail={'net_pnl_cents': r.net_pnl} if r.net_pnl is not None else {})
        for r in db.execute(select(DebitSpreadPosition.id, DebitSpreadPosition.signal_id, DebitSpreadPosition.status,
            DebitSpreadPosition.detail['net_pnl_cents'].as_integer().label('net_pnl')).where(
            DebitSpreadPosition.account_key == KEY,
            DebitSpreadPosition.detail['entry_at'].as_string().is_not(None)))]
    # Preserve full matched-entry denominator, including open and unpriced pairs.
    baseline_entries = set(db.scalars(select(ForwardPaperEvent.detail['position_id'].as_integer()).where(
        ForwardPaperEvent.account_key == BASELINE, ForwardPaperEvent.kind == 'ENTRY',
        ForwardPaperEvent.occurred_at >= account.activated_at)))
    spread_entries = set(db.scalars(select(DebitSpreadEvent.detail['position_id'].as_integer()).where(
        DebitSpreadEvent.account_key == KEY, DebitSpreadEvent.kind == 'ENTRY')))
    full = db.execute(select(func.coalesce(func.sum(ForwardPaperEvent.settled_cents), 0),
        func.coalesce(func.sum(ForwardPaperEvent.unsettled_cents), 0),
        func.coalesce(func.sum(ForwardPaperEvent.realized_cents), 0)).where(
        ForwardPaperEvent.account_key == BASELINE)).one()
    baseline = {p.signal_id: p for p in db.scalars(select(ForwardPaperPosition).where(
        ForwardPaperPosition.account_key == BASELINE,
        ForwardPaperPosition.signal_id.in_([p.signal_id for p in paired_rows] or [''])))
        if p.id in baseline_entries and p.detail.get('entry_at')
        and utc(datetime.fromisoformat(p.detail['entry_at'])) >= utc(account.activated_at)}
    matched = [p for p in paired_rows if p.id in spread_entries and p.signal_id in baseline]
    complete = [p for p in matched if p.status in ('CLOSED', 'UNSETTLED')
                and baseline[p.signal_id].status in ('CLOSED', 'UNSETTLED')
                and 'net_pnl_cents' in p.detail and 'net_pnl_cents' in baseline[p.signal_id].detail]
    pages = max(1, math.ceil(total/20));page = min(max(1, page), pages)
    visible = list(db.scalars(select(DebitSpreadPosition).where(DebitSpreadPosition.account_key == KEY)
        .order_by(DebitSpreadPosition.id.desc()).offset((page-1)*20).limit(20)))
    display_fields = ('ticker', 'trading_date', 'mode', 'expiration', 'long', 'short', 'reason',
                      'entry_at', 'exit_at', 'entry_debit_cents', 'exit_credit_cents', 'net_pnl_cents')
    event_counts = dict(db.execute(select(DebitSpreadEvent.kind, func.count()).where(
        DebitSpreadEvent.account_key == KEY).group_by(DebitSpreadEvent.kind)).all())
    return {**common, 'status': 'ACTIVE' if common['enabled'] else 'PAUSED',
        'activated_at': utc(account.activated_at).isoformat(), 'processed_at': utc(account.processed_at).isoformat(),
        'policy': account.policy, 'settled_cents': settled, 'unsettled_cents': unsettled,
        'available_cents': available, 'realized_cents': realized,
        'equity_cents': None if unknown else settled+unsettled+credits, 'unknown_positions': unknown,
        'held_positions': len(held), 'pending_positions': counts.get('PENDING_ENTRY', 0),
        'skips': counts.get('SKIPPED', 0), 'opportunities': total,
        'entry_quote_coverage': {'requested': db.scalar(select(func.count()).select_from(DebitSpreadEvent).where(
            DebitSpreadEvent.account_key == KEY, DebitSpreadEvent.kind == 'ENTRY_REQUEST')) or 0,
            'quoted': db.scalar(select(func.count()).select_from(DebitSpreadEvent).where(
                DebitSpreadEvent.account_key == KEY, DebitSpreadEvent.kind == 'ENTRY_QUOTE_AVAILABLE')) or 0,
                                 'filled': event_counts.get('ENTRY', 0)},
        'exit_quote_coverage': {'quoted': db.scalar(select(func.count()).select_from(DebitSpreadEvent).where(
            DebitSpreadEvent.account_key == KEY, DebitSpreadEvent.kind == 'EXIT_QUOTE_AVAILABLE')) or 0,
            'requested': db.scalar(select(func.count()).select_from(DebitSpreadEvent).where(
            DebitSpreadEvent.account_key == KEY, DebitSpreadEvent.kind == 'EXIT_REQUEST')) or 0,
            'filled': event_counts.get('EXIT', 0)},
        'baseline_full_cash': {'account_key': BASELINE, 'settled_cents': int(full[0]),
            'unsettled_cents': int(full[1]), 'realized_cents': int(full[2]),
            'basis': 'INDEPENDENT_LIFETIME_CASH_NOT_MATCHED_PERIOD'},
        'matched': {'entered_pairs': len(matched), 'closed_priced_pairs': len(complete),
            'unresolved_pairs': len(matched)-len(complete), 'complete': len(matched) > 0 and len(matched) == len(complete),
            'spread_closed_subset_pnl_cents': sum(p.detail['net_pnl_cents'] for p in complete),
            'baseline_closed_subset_pnl_cents': sum(baseline[p.signal_id].detail['net_pnl_cents'] for p in complete)},
        'history': [{'at': utc(s.at).isoformat(), 'equity_cents': s.equity, 'cash_cents': s.cash,
                     'unknown': s.unknown} for s in snaps],
        'page': page, 'pages': pages, 'positions': [{'id': p.id, 'status': p.status,
            **{k: p.detail[k] for k in display_fields if k in p.detail}} for p in visible],
        'as_of': now.isoformat()}
