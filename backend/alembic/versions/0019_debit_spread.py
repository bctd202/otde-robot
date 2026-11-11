"""Add isolated, unfunded debit-spread research storage."""
from alembic import op
from app.db.models import DebitSpreadAccount, DebitSpreadPosition, DebitSpreadEvent, DebitSpreadSnapshot

revision = '0019_debit_spread'
down_revision = '0018_retest_research'
branch_labels = None
depends_on = None


def upgrade():
    for model in (DebitSpreadAccount, DebitSpreadPosition, DebitSpreadEvent, DebitSpreadSnapshot):
        model.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError('Preserve prospective spread evidence; routine destructive downgrade is disabled')
