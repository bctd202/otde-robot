"""Read-only, explicitly approved main-account research cohort; never buying power.

The Nov 4 user decision excludes exactly the three trades in the previously
approved write-off batch. This does not label every quote gap as bad input, does
not erase an entry, and does not replay the account as if it had extra capital.
"""
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy import func, select

from app.db.models import ForwardPaperEquitySnapshot, ForwardPaperEvent, ForwardPaperPosition
from app.services import forward_account as baseline
from app.services.option_research import utc
from app.services.paper_writeoffs import ACCOUNT_KEY, EVENT, STATUS, identity

VERSION = 'approved-data-exclusions-20261104-v1'
APPROVAL_REQUEST_SHA256 = '76f7568135305086174c92b33d7c194cfef02e5b9d2f242a0b5090fb04b97056'
EXPECTED_COUNT = 3
EXPECTED_DEBIT_CENTS = 17950
REASON = 'Excluded by operator: no verified exit data; outcome cannot be scored.'


def approved_scope(db, account_key: str) -> dict:
    """No broad status filter: unrelated/future write-offs remain included."""
    empty = {'version': VERSION, 'state': 'NOT_APPLICABLE', 'excluded_count': 0,
             'excluded_debit_cents': 0, 'positions': [], 'reason': REASON}
    if account_key != ACCOUNT_KEY:
        return empty
    events = list(db.scalars(select(ForwardPaperEvent).where(
        ForwardPaperEvent.account_key == account_key, ForwardPaperEvent.kind == EVENT,
        ForwardPaperEvent.detail['request_sha256'].as_string() == APPROVAL_REQUEST_SHA256)
        .order_by(ForwardPaperEvent.id)))
    if not events:
        return empty
    positions = []
    for event in events:
        p = db.get(ForwardPaperPosition, event.detail.get('position_id'))
        original = event.detail.get('original_detail', {})
        adjustment = p.detail.get('manual_write_off', {}) if p is not None else {}
        if (p is None or p.account_key != account_key or p.status != STATUS
                or adjustment.get('request_sha256') != APPROVAL_REQUEST_SHA256
                or p.detail.get('option_symbol') != event.detail.get('option_symbol')
                or p.detail.get('entry_debit_cents') != -event.realized_cents
                or original.get('entry_debit_cents') != -event.realized_cents
                or identity(original) != event.detail.get('original_detail_sha256')
                or identity({k: v for k, v in p.detail.items() if k != 'manual_write_off'})
                    != event.detail.get('original_detail_sha256')
                or adjustment.get('actual_exit_verified') is not False
                or event.detail.get('assumed_proceeds_cents') != 0
                or not original.get('entry_at') or event.settled_cents or event.unsettled_cents
                or any(k in p.detail for k in ('sale_cents', 'exit_quote'))):
            return {**empty, 'state': 'SCOPE_REQUIRES_REVIEW'}
        try:
            utc(datetime.fromisoformat(original['entry_at']))
        except (TypeError, ValueError):
            return {**empty, 'state': 'SCOPE_REQUIRES_REVIEW'}
        positions.append({'id': p.id, 'option_symbol': p.detail['option_symbol'],
                          'entry_debit_cents': p.detail['entry_debit_cents'],
                          'entry_at': p.detail['entry_at'], 'reason': REASON})
    if (len(positions) != EXPECTED_COUNT or len({p['id'] for p in positions}) != EXPECTED_COUNT
            or sum(p['entry_debit_cents'] for p in positions) != EXPECTED_DEBIT_CENTS):
        return {**empty, 'state': 'SCOPE_REQUIRES_REVIEW'}
    return {**empty, 'state': 'APPLIED_TO_RESEARCH_VIEW', 'excluded_count': len(positions),
            'excluded_debit_cents': EXPECTED_DEBIT_CENTS, 'positions': positions}


def _credit(scope: dict, at: datetime) -> int:
    return sum(p['entry_debit_cents'] for p in scope['positions']
               if utc(datetime.fromisoformat(p['entry_at'])) <= utc(at))


def _value(positions: list[Any], policy: dict, at: datetime) -> dict:
    result = baseline._valuation(positions, policy, utc(at))
    result['unpriced_positions'] += sum(p.status == 'ENDED_UNRESOLVED' for p in positions)
    return result


def research_history(db, account, scope: dict, now: datetime) -> dict:
    """Derive a separate cohort curve from saved cash and captured valuation evidence.

    Never update a snapshot or carry prices through missing evidence. A null may
    become calculable ONLY when all its unknown exposure was explicitly excluded
    and the retained positions have sufficient timestamp-bound evidence.
    """
    model = ForwardPaperEquitySnapshot
    daily_ids = select(func.max(model.id)).where(model.account_key == account.key,
        model.observed_at <= utc(now)).group_by(model.trading_date)
    columns = (model.observed_at, model.trading_date, model.cash_cents, model.equity_cents,
               model.unpriced_positions, model.detail)
    daily = db.execute(select(*columns).where(model.id.in_(daily_ids))
                       .order_by(model.observed_at)).all()
    intraday = db.execute(select(*columns).where(model.account_key == account.key,
        model.trading_date == daily[-1].trading_date, model.observed_at <= utc(now))
        .order_by(model.observed_at)).all() if daily else []
    # Only small monetary fields, not every position's full strategy/quote JSON.
    costs = {r.id: {'entry_debit_cents': r.debit, 'entry_fee_cents': r.fee,
                   'entry_at': r.entry_at, 'exit_at': r.exit_at, 'write_off_at': r.write_off_at} for r in db.execute(
        select(ForwardPaperPosition.id, ForwardPaperPosition.detail['entry_debit_cents'].as_integer().label('debit'),
               ForwardPaperPosition.detail['entry_fee_cents'].as_integer().label('fee'),
               ForwardPaperPosition.detail['entry_at'].as_string().label('entry_at'),
               ForwardPaperPosition.detail['exit_at'].as_string().label('exit_at'),
               ForwardPaperPosition.detail['manual_write_off']['at'].as_string().label('write_off_at'))
        .where(ForwardPaperPosition.account_key == account.key))}
    intervals_valid = True
    try:
        intervals = {key: (utc(datetime.fromisoformat(value['entry_at'])),
                          min((utc(datetime.fromisoformat(value[k])) for k in ('exit_at', 'write_off_at')
                               if value[k]), default=None))
                     for key, value in costs.items() if value['entry_at']}
    except (TypeError, ValueError):
        intervals, intervals_valid = {}, False
    excluded = {p['id'] for p in scope['positions']}
    funding = account.policy['starting_cash_cents']

    def point(row):
        at = utc(row.observed_at)
        equity = None
        unknown = row.unpriced_positions
        reconstructed = False
        captured = (row.detail or {}).get('positions')
        if (intervals_valid and isinstance(captured, list)
                and all(isinstance(p, dict) and type(p.get('id')) is int for p in captured)
                and len({p['id'] for p in captured}) == len(captured)
                and {p['id'] for p in captured} == {
                    key for key, (entry, end) in intervals.items() if entry <= at and (end is None or at < end)}):
            stubs: list[Any] = []
            valid = True
            for item in captured:
                if (not isinstance(item, dict) or item.get('id') not in costs
                        or item.get('status') not in {'OPEN', 'UNPRICED', 'ENDED_UNRESOLVED'}):
                    valid = False
                    break
                stubs.append(SimpleNamespace(id=item['id'], status=item['status'],
                    detail={**costs[item['id']], 'valuation': item.get('valuation')}))
            if valid:
                try:
                    original = _value(stubs, account.policy, at)
                    retained = _value([p for p in stubs if p.id not in excluded], account.policy, at)
                    consistent = original['unpriced_positions'] == row.unpriced_positions
                    if row.equity_cents is not None:
                        consistent = consistent and row.cash_cents + original['known_liquidation_cents'] == row.equity_cents
                    if consistent:
                        unknown = retained['unpriced_positions']
                        if unknown == 0:
                            equity = row.cash_cents + retained['known_liquidation_cents'] + _credit(scope, at)
                            reconstructed = row.equity_cents is None
                except (KeyError, TypeError, ValueError, OverflowError):
                    pass  # Insufficient retained evidence stays a gap, never a guessed return.
        return {'at': at.isoformat(), 'date': row.trading_date.isoformat(),
                'equity_cents': equity, 'return_percent': None if equity is None else
                round((equity-funding)/funding*100, 6), 'unpriced_positions': unknown,
                'basis': 'DERIVED_RESEARCH_COHORT_NOT_ACCOUNT_EQUITY',
                'source_equity_cents': row.equity_cents, 'reconstructed_from_saved_evidence': reconstructed}

    first = db.scalar(select(func.min(model.observed_at)).where(model.account_key == account.key))
    return {'baseline_cents': funding, 'started_at': utc(first).isoformat() if first else None,
            'daily': [point(row) for row in daily], 'intraday': [point(row) for row in intraday],
            'basis': 'Derived included-trade research value, excluding the approved entry debits and option exposure. '
                     'Not spendable cash or an account return. Original snapshots unchanged; no capacity replay.'}


def research_summary(db, account, scope: dict, *, now: datetime,
                     account_equity_cents: int | None, realized_cents: int) -> dict | None:
    if not scope['excluded_count']:
        return None
    equity = None if account_equity_cents is None else account_equity_cents + _credit(scope, now)
    return {'version': VERSION, 'excluded_count': scope['excluded_count'],
            'excluded_debit_cents': scope['excluded_debit_cents'],
            'equity_cents': equity, 'realized_cents': realized_cents + scope['excluded_debit_cents'],
            'equity_history': research_history(db, account, scope, now),
            'basis': 'ADJUSTED_RESEARCH_VALUE_NOT_CASH', 'cash_ledger_changed': False,
            'capacity_replayed': False, 'reason': REASON}
