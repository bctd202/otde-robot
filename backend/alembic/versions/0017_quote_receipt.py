"""Add prospective quote-receipt evidence; never infer historical arrival times."""
from alembic import op
import sqlalchemy as sa

revision = '0017_quote_receipt'
down_revision = '0016_lotto_trials'
branch_labels = None
depends_on = None


def upgrade():
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('lottery_quote_snapshots')}
    if 'receipt_evidence' not in columns:
        op.add_column('lottery_quote_snapshots', sa.Column('receipt_evidence', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('lottery_quote_snapshots') as batch:
        batch.drop_column('receipt_evidence')
