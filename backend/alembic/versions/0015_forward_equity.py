"""Forward observed equity only; no historical cash or trade backfill."""
from alembic import op
import sqlalchemy as sa

revision = "0015_forward_equity"
down_revision = "0014_forward_paper_account"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "forward_paper_equity_snapshots" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table("forward_paper_equity_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_key", sa.String(48), sa.ForeignKey("forward_paper_accounts.key"), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("cash_cents", sa.Integer(), nullable=False),
        sa.Column("equity_cents", sa.Integer(), nullable=True),
        sa.Column("unpriced_positions", sa.Integer(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.UniqueConstraint("account_key", "observed_at", name="uq_forward_equity_observation"))
    op.create_index("ix_forward_equity_account_day", "forward_paper_equity_snapshots",
                    ["account_key", "trading_date", "id"])


def downgrade() -> None:
    op.drop_table("forward_paper_equity_snapshots")
