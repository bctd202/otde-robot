"""Isolated prospective research tables. No funding or historical imports."""
from alembic import op
from app.db.models import (RetestRun, RetestAccount, RetestOpportunity, RetestPosition,
                           RetestEvent, RetestObservation)

revision = '0018_retest_research'
down_revision = '0017_quote_receipt'
branch_labels = None
depends_on = None
TABLES = (RetestRun, RetestAccount, RetestOpportunity, RetestPosition, RetestEvent, RetestObservation)


def upgrade():
    for model in TABLES:
        model.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    # Never silently discard forward evidence through a routine rollback.
    raise RuntimeError('Research evidence must be archived/reviewed; downgrade is intentionally disabled')
