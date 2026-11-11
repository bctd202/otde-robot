"""Bounded optional hook: disabled is a no-op; failures cannot undo baseline work."""
import logging
from app.core.config import get_settings

logger = logging.getLogger(__name__)


def run(db, provider=None, *, now=None):
    if not get_settings().debit_spread_enabled:
        return
    try:
        from app.services.debit_spread_account import advance
        with db.begin_nested():
            advance(db, provider, now=now)
    except Exception:
        logger.exception('Optional debit-spread research failed; existing tests retained')
