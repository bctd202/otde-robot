"""Add forward-only option path evidence; never backfill entry/exit records."""
from alembic import op
import sqlalchemy as sa

revision = "0013_option_observations"
down_revision = "0012_scanner_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 builds Base.metadata, so a clean install already has current tables.
    if "automated_option_observations" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "automated_option_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("signal_id", sa.String(36), sa.ForeignKey("signal_performance.signal_id"), nullable=False),
        sa.Column("minute_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("option_symbol", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("bid", sa.Float(), nullable=True),
        sa.Column("ask", sa.Float(), nullable=True),
        sa.Column("bid_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ask_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("cohort", sa.String(64), nullable=False),
        sa.UniqueConstraint("signal_id", "minute_at", name="uq_option_observation_minute"),
    )
    op.create_index("ix_automated_option_observations_signal_id", "automated_option_observations", ["signal_id"])


def downgrade() -> None:
    op.drop_table("automated_option_observations")
