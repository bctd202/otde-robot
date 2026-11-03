"""Explicit operator-approved paper adjustments, never verified sales or automatic expiry.

Only the independent ten-position account is supported. Original events, quotes,
signal outcomes and equity observations are not edited. The caller commits the
new immutable adjustment events and the mutable position projection together.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import AutomatedOptionMark, ForwardPaperAccount, ForwardPaperEvent, ForwardPaperPosition
from app.services.option_research import utc
from app.services.paper_lifecycle import ENDED_UNRESOLVED, final_session_end

VERSION = 'manual-zero-write-off-v1'
ACCOUNT_KEY = 'tasty-capacity-ten-v1'
STATUS = 'WRITTEN_OFF'
EVENT = 'MANUAL_WRITE_OFF'


def identity(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def _events(db: Session, account_key: str) -> list[ForwardPaperEvent]:
    return list(db.scalars(select(ForwardPaperEvent).where(
        ForwardPaperEvent.account_key == account_key, ForwardPaperEvent.kind == EVENT)
        .order_by(ForwardPaperEvent.id)))


def adjustment_summary(db: Session, account_key: str) -> dict:
    """Read-only; actual missing exit evidence is not repaired by an assumption."""
    events = _events(db, account_key)
    return {
        'version': VERSION, 'count': len(events),
        'loss_cents': -sum(e.realized_cents for e in events),
        'first_recorded_at': utc(events[0].occurred_at).isoformat() if events else None,
        'last_recorded_at': utc(events[-1].occurred_at).isoformat() if events else None,
        'verified_exit_evidence': False if events else None,
        'historical_snapshots_rewritten': False,
        'adjustments': [{'event_id': e.id, 'at': utc(e.occurred_at).isoformat(),
                         'position_id': e.detail['position_id'],
                         'option_symbol': e.detail['option_symbol'],
                         'loss_cents': -e.realized_cents,
                         'assumed_proceeds_cents': 0, 'approval_ref': e.detail['approval_ref']}
                        for e in events],
    }


def prepare_request(db: Session, *, symbols: list[str], expected_total_cents: int,
                    approval_ref: str) -> dict:
    """Exact targets only. New/future unknown exits can never enter this request."""
    if (not symbols or len(symbols) > 10 or len(set(symbols)) != len(symbols)
            or type(expected_total_cents) is not int or expected_total_cents <= 0
            or not isinstance(approval_ref, str) or not 1 <= len(approval_ref) <= 256):
        raise ValueError('Explicit distinct symbols, positive total and approval reference required')
    positions = list(db.scalars(select(ForwardPaperPosition).where(
        ForwardPaperPosition.account_key == ACCOUNT_KEY,
        ForwardPaperPosition.status == ENDED_UNRESOLVED)))
    targets = []
    for symbol in sorted(symbols):
        matches = [p for p in positions if p.detail.get('option_symbol') == symbol]
        if len(matches) != 1:
            raise ValueError('Target is not one uniquely identified ended unresolved position')
        position = matches[0]
        targets.append({'position_id': position.id, 'option_symbol': symbol,
                        'entry_debit_cents': position.detail['entry_debit_cents'],
                        'original_detail_sha256': identity(position.detail)})
    if sum(p['entry_debit_cents'] for p in targets) != expected_total_cents:
        raise ValueError('Exact approved cost total does not match; no automatic expansion')
    return {'version': VERSION, 'account_key': ACCOUNT_KEY, 'approval_ref': approval_ref,
            'expected_total_cents': expected_total_cents, 'targets': targets}


def apply_request(db: Session, request: dict, *, now: datetime | None = None) -> dict:
    """Atomic, hash-bound, retry-safe; never refunds principal or creates proceeds."""
    from app.services import expanded_account

    if not get_settings().paper_only:
        raise ValueError('Paper-only configuration is required')
    required = {'version', 'account_key', 'approval_ref', 'expected_total_cents', 'targets'}
    if (set(request) != required or request['version'] != VERSION
            or request['account_key'] != ACCOUNT_KEY
            or not isinstance(request['approval_ref'], str)
            or not 1 <= len(request['approval_ref']) <= 256
            or not isinstance(request['targets'], list) or not 1 <= len(request['targets']) <= 10):
        raise ValueError('Invalid or unsupported explicit write-off request')
    targets = request['targets']
    fields = {'position_id', 'option_symbol', 'entry_debit_cents', 'original_detail_sha256'}
    if any(not isinstance(t, dict) or set(t) != fields or type(t['position_id']) is not int
           or type(t['entry_debit_cents']) is not int or t['entry_debit_cents'] <= 0
           for t in targets):
        raise ValueError('Malformed exact position targets')
    if (len({t['position_id'] for t in targets}) != len(targets)
            or type(request['expected_total_cents']) is not int
            or sum(t['entry_debit_cents'] for t in targets) != request['expected_total_cents']):
        raise ValueError('Duplicate targets or cost mismatch')
    now = utc(now or datetime.now(timezone.utc))
    request_hash = identity(request)
    connection = db.connection()
    driver = connection.connection.driver_connection
    if driver is None:
        raise ValueError('Database connection is unavailable')
    if connection.dialect.name == 'sqlite' and not driver.in_transaction:
        # Legacy sqlite transaction mode must not let RELEASE SAVEPOINT commit
        # a supposedly caller-owned transaction before the explicit db.commit().
        connection.exec_driver_sql('BEGIN IMMEDIATE')
    with db.begin_nested():
        # Serialize with the scanner's account writer before checking any projection.
        locked = db.execute(update(ForwardPaperAccount).where(
            ForwardPaperAccount.key == ACCOUNT_KEY).values(
                revision=ForwardPaperAccount.revision + 1))
        if locked.rowcount != 1:
            raise ValueError('Account is not active')
        account = db.get(ForwardPaperAccount, ACCOUNT_KEY)
        if account is None:
            raise ValueError('Account disappeared during adjustment')
        db.refresh(account)
        if now < utc(account.processed_at):
            raise ValueError('Write-offs cannot be backdated before account processing')
        planned = []
        for target in targets:
            position = db.get(ForwardPaperPosition, target['position_id'])
            if position is None or position.account_key != ACCOUNT_KEY:
                raise ValueError('Wrong account or missing position')
            db.refresh(position)
            key = f"{position.id}:{VERSION}"
            prior = db.scalar(select(ForwardPaperEvent).where(
                ForwardPaperEvent.account_key == ACCOUNT_KEY, ForwardPaperEvent.event_key == key))
            if prior:
                if (prior.kind != EVENT or prior.detail.get('request_sha256') != request_hash
                        or position.status != STATUS
                        or position.detail.get('manual_write_off', {}).get('request_sha256') != request_hash
                        or identity({k: v for k, v in position.detail.items() if k != 'manual_write_off'})
                        != target['original_detail_sha256']):
                    raise ValueError('Conflicting or partial previous adjustment; manual review required')
                continue
            detail = position.detail
            mark = db.get(AutomatedOptionMark, position.entry_mark_id)
            entry = db.scalar(select(ForwardPaperEvent).where(
                ForwardPaperEvent.account_key == ACCOUNT_KEY,
                ForwardPaperEvent.event_key == f'{position.id}:entry', ForwardPaperEvent.kind == 'ENTRY'))
            if (position.status != ENDED_UNRESOLVED or mark is None or now < final_session_end(mark)
                    or detail.get('option_symbol') != target['option_symbol']
                    or detail.get('entry_debit_cents') != target['entry_debit_cents']
                    or identity(detail) != target['original_detail_sha256']
                    or any(k in detail for k in ('sale_cents', 'exit_quote', 'manual_write_off'))
                    or entry is None or entry.settled_cents != -target['entry_debit_cents']
                    or entry.detail.get('entry_debit_cents') != target['entry_debit_cents']):
                raise ValueError('Position/evidence changed or a real sale exists; write-off refused')
            planned.append((position, key, deepcopy(detail)))
        for position, key, original in planned:
            adjustment = {'version': VERSION, 'at': now.isoformat(),
                          'approval_ref': request['approval_ref'], 'request_sha256': request_hash,
                          'original_detail_sha256': identity(original),
                          'assumed_proceeds_cents': 0, 'modeled_loss_cents': original['entry_debit_cents'],
                          'actual_exit_verified': False,
                          'reason': 'Operator-approved full-loss assumption; not a sale or proven worthless expiry'}
            db.add(ForwardPaperEvent(
                account_key=ACCOUNT_KEY, event_key=key, occurred_at=now, kind=EVENT,
                settled_cents=0, unsettled_cents=0, fee_cents=0,
                realized_cents=-original['entry_debit_cents'],
                detail={'position_id': position.id, 'ticker': original.get('ticker'),
                        'option_symbol': original['option_symbol'], **adjustment,
                        'original_status': ENDED_UNRESOLVED, 'original_detail': original}))
            position.status = STATUS
            position.detail = {**original, 'manual_write_off': adjustment}
        db.flush()
        if planned:
            # A queued scanner tick observed before this adjustment cannot later
            # publish the new assumptions under an earlier observation clock.
            account.processed_at = now
            # A new current observation only; never fill old null observations retroactively.
            # If this exact scanner timestamp already exists, its old value stays untouched.
            expanded_account._record_equity_snapshot(db, account, now)
        return {'request_sha256': request_hash, 'applied': len(planned),
                'already_applied': len(targets)-len(planned),
                'loss_cents': sum(p.detail['entry_debit_cents'] for p, _, _ in planned),
                'cash_delta_cents': 0, 'historical_evidence_changed': False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    plan = sub.add_parser('plan')
    plan.add_argument('--symbol', action='append', required=True)
    plan.add_argument('--expected-total-cents', type=int, required=True)
    plan.add_argument('--approval-ref', required=True)
    apply = sub.add_parser('apply')
    apply.add_argument('--request', type=Path, required=True)
    args = parser.parse_args()
    from app.db.session import SessionLocal
    with SessionLocal() as db:
        if args.operation == 'plan':
            result = prepare_request(db, symbols=args.symbol, expected_total_cents=args.expected_total_cents,
                                     approval_ref=args.approval_ref)
        else:
            if args.request.stat().st_size > 65536 or args.request.is_symlink():
                raise ValueError('Unsafe adjustment request file')
            result = apply_request(db, json.loads(args.request.read_text()))
            db.commit()
        print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
