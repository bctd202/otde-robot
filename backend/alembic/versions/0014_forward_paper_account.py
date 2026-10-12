"""Separate forward cash ledger. No historical trades or balances are imported."""
from alembic import op
import sqlalchemy as sa

revision = "0014_forward_paper_account"
down_revision = "0013_option_observations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "forward_paper_accounts" not in existing:
        op.create_table("forward_paper_accounts",
            sa.Column("key", sa.String(48), primary_key=True),
            sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("mark_watermark", sa.Integer(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("policy", sa.JSON(), nullable=False))
    if "forward_paper_positions" not in existing:
        op.create_table("forward_paper_positions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("account_key", sa.String(48), sa.ForeignKey("forward_paper_accounts.key"), nullable=False),
            sa.Column("signal_id", sa.String(36), sa.ForeignKey("signal_performance.signal_id"), nullable=False),
            sa.Column("entry_mark_id", sa.Integer(), sa.ForeignKey("automated_option_marks.id"), nullable=False),
            sa.Column("status", sa.String(24), nullable=False),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("detail", sa.JSON(), nullable=False),
            sa.UniqueConstraint("account_key", "signal_id", name="uq_forward_account_signal"))
        op.create_index("ix_forward_paper_positions_account_key", "forward_paper_positions", ["account_key"])
        op.create_index("ix_forward_paper_positions_status", "forward_paper_positions", ["status"])
    if "forward_paper_events" not in existing:
        op.create_table("forward_paper_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("account_key", sa.String(48), sa.ForeignKey("forward_paper_accounts.key"), nullable=False),
            sa.Column("event_key", sa.String(96), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("kind", sa.String(24), nullable=False),
            sa.Column("settled_cents", sa.Integer(), nullable=False),
            sa.Column("unsettled_cents", sa.Integer(), nullable=False),
            sa.Column("fee_cents", sa.Integer(), nullable=False),
            sa.Column("realized_cents", sa.Integer(), nullable=False),
            sa.Column("detail", sa.JSON(), nullable=False),
            sa.UniqueConstraint("account_key", "event_key", name="uq_forward_account_event"))
        op.create_index("ix_forward_paper_events_account_key", "forward_paper_events", ["account_key"])


def downgrade() -> None:
    for table in ("forward_paper_events", "forward_paper_positions", "forward_paper_accounts"):
        op.drop_table(table)
