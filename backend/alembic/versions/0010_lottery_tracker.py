"""add scan-by-scan lottery contract tracking

Revision ID: 0010_lottery_tracker
Revises: 0009_trading_modes
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_lottery_tracker"
down_revision = "0009_trading_modes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "lottery_trackers" not in tables:
        op.create_table(
            "lottery_trackers",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("trading_date", sa.Date(), nullable=False),
            sa.Column("symbol", sa.String(12), nullable=False),
            sa.Column("option_symbol", sa.String(64), nullable=False),
            sa.Column("normalized_option_symbol", sa.String(64), nullable=True),
            sa.Column("expiration", sa.Date(), nullable=False),
            sa.Column("right", sa.String(8), nullable=False),
            sa.Column("strike", sa.Float(), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_qualified_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_quote_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("entry_ask", sa.Float(), nullable=False),
            sa.Column("entry_bid", sa.Float(), nullable=False),
            sa.Column("entry_underlying_price", sa.Float(), nullable=False),
            sa.Column("setup_score", sa.Float(), nullable=False),
            sa.Column("initial_snapshot", sa.JSON(), nullable=False),
            sa.Column("provider", sa.String(32), nullable=False),
            sa.Column("data_mode", sa.String(32), nullable=False),
            sa.Column("verification_status", sa.String(32), nullable=False),
            sa.Column("verification_reason", sa.String(255), nullable=False),
            sa.Column("actionable", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("latest_bid", sa.Float(), nullable=True),
            sa.Column("latest_ask", sa.Float(), nullable=True),
            sa.Column("latest_midpoint", sa.Float(), nullable=True),
            sa.Column("latest_last", sa.Float(), nullable=True),
            sa.Column("latest_underlying_price", sa.Float(), nullable=True),
            sa.Column("peak_bid", sa.Float(), nullable=False, server_default="0"),
            sa.Column("peak_bid_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("hit_2x_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("hit_5x_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("hit_10x_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("trading_date", "option_symbol", name="uq_lottery_tracker_date_contract"),
        )
        op.create_index("ix_lottery_trackers_trading_date", "lottery_trackers", ["trading_date"])
        op.create_index("ix_lottery_trackers_symbol", "lottery_trackers", ["symbol"])
        op.create_index("ix_lottery_trackers_option_symbol", "lottery_trackers", ["option_symbol"])
        op.create_index("ix_lottery_trackers_status", "lottery_trackers", ["status"])
        op.create_index("ix_lottery_trackers_date_status", "lottery_trackers", ["trading_date", "status"])

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "lottery_quote_snapshots" not in tables:
        op.create_table(
            "lottery_quote_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tracker_id", sa.String(36), sa.ForeignKey("lottery_trackers.id"), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("quote_timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("bid_timestamp", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ask_timestamp", sa.DateTime(timezone=True), nullable=True),
            sa.Column("bid", sa.Float(), nullable=False),
            sa.Column("ask", sa.Float(), nullable=False),
            sa.Column("midpoint", sa.Float(), nullable=False),
            sa.Column("last", sa.Float(), nullable=False),
            sa.Column("underlying_price", sa.Float(), nullable=True),
            sa.Column("spread_percent", sa.Float(), nullable=False),
            sa.Column("volume", sa.Integer(), nullable=False),
            sa.Column("open_interest", sa.Integer(), nullable=False),
            sa.Column("delta", sa.Float(), nullable=True),
            sa.Column("gamma", sa.Float(), nullable=True),
            sa.Column("theta", sa.Float(), nullable=True),
            sa.Column("iv", sa.Float(), nullable=True),
            sa.Column("is_qualified", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("setup_score", sa.Float(), nullable=True),
            sa.UniqueConstraint("tracker_id", "observed_at", name="uq_lottery_snapshot_tracker_observed"),
        )
        op.create_index("ix_lottery_quote_snapshots_tracker_id", "lottery_quote_snapshots", ["tracker_id"])
        op.create_index("ix_lottery_quote_snapshots_observed_at", "lottery_quote_snapshots", ["observed_at"])
        op.create_index(
            "ix_lottery_quote_tracker_observed",
            "lottery_quote_snapshots",
            ["tracker_id", "observed_at"],
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "lottery_quote_snapshots" in tables:
        op.drop_table("lottery_quote_snapshots")
    if "lottery_trackers" in tables:
        op.drop_table("lottery_trackers")
