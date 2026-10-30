"""Append-only transport evidence, without evaluating new trading decisions."""
from datetime import datetime, timedelta, timezone
import json

from sqlalchemy import select

from app.db.models import DataQualityEvent
from app.services.market_calendar import NY, is_market_day, market_close

VERSION = 'collection-integrity-v2'


def snapshot(provider, evaluation: datetime) -> dict:
    try:
        inputs = provider.completed_candle_evidence(evaluation) if hasattr(provider,'completed_candle_evidence') else {}
        if not isinstance(inputs,dict):
            raise ValueError('Invalid input evidence')
        return {'version':VERSION,'evaluation_at':evaluation.isoformat(),
                'inputs':{k:v is True for k,v in inputs.items()}}
    except Exception as exc:
        # Optional diagnostics cannot roll back completed baseline decisions.
        return {'version':VERSION,'evaluation_at':evaluation.isoformat(),
                'inputs':{},'error_type':type(exc).__name__}


def record_close(db, provider, now: datetime) -> None:
    local = now.astimezone(NY)
    if not is_market_day(local.date()) or provider is None:
        return
    close = datetime.combine(local.date(),market_close(local.date()),NY)
    if not close <= local <= close+timedelta(minutes=3):
        return
    tag = f'collection-close:{local.date()}'
    # Called under scanner's exclusive lock. Inspecting an endpoint never calls it.
    if db.scalar(select(DataQualityEvent.id).where(DataQualityEvent.provider==tag)):
        return
    payload = snapshot(provider,(close-timedelta(minutes=1)).astimezone(timezone.utc))
    db.add(DataQualityEvent(provider=tag,severity='INFO',message=json.dumps(payload),timestamp=now))
