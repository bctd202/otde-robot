"""Add empty, observational entry-price-limit evidence; never fund or backfill."""
from alembic import op
from app.db.models import EntryCapReviewEvent

revision = '0020_entry_cap_review'
down_revision = '0019_debit_spread'
branch_labels = None
depends_on = None


def upgrade():
    EntryCapReviewEvent.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError('Preserve entry-cap research evidence; destructive downgrade disabled')
