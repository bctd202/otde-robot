"""add forward-only automated option entry and exit marks

Revision ID: 0011_automated_option_marks
Revises: 0010_lottery_tracker
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_automated_option_marks"
down_revision = "0010_lottery_tracker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "automated_option_marks" in tables:
        return
    op.create_table(
        "automated_option_marks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("signal_id", sa.String(36), sa.ForeignKey("signal_performance.signal_id"), nullable=False),
        sa.Column("position_key", sa.String(32), nullable=True),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("ticker", sa.String(12), nullable=False),
        sa.Column("strategy_mode", sa.String(32), nullable=False),
        sa.Column("mark_type", sa.String(8), nullable=False),
        sa.Column("mark_status", sa.String(32), nullable=False),
        sa.Column("event_reason", sa.String(32), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("option_symbol", sa.String(64), nullable=False),
        sa.Column("normalized_option_symbol", sa.String(64), nullable=False),
        sa.Column("expiration", sa.Date(), nullable=False),
        sa.Column("strike", sa.Float(), nullable=False),
        sa.Column("right", sa.String(8), nullable=False),
        sa.Column("bid", sa.Float(), nullable=True),
        sa.Column("ask", sa.Float(), nullable=True),
        sa.Column("last", sa.Float(), nullable=True),
        sa.Column("quote_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bid_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ask_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("selected_price", sa.Float(), nullable=True),
        sa.Column("price_basis", sa.String(16), nullable=False),
        sa.Column("quote_lag_seconds", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("data_mode", sa.String(32), nullable=False),
        sa.Column("verification_status", sa.String(32), nullable=False),
        sa.Column("verification_reason", sa.String(255), nullable=False),
        sa.Column("contract_multiplier", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("signal_id", "mark_type", name="uq_automated_option_signal_mark"),
        sa.UniqueConstraint("position_key", name="uq_automated_option_position_key"),
    )
    op.create_index("ix_automated_option_marks_signal_id", "automated_option_marks", ["signal_id"])
    op.create_index("ix_automated_option_marks_trading_date", "automated_option_marks", ["trading_date"])
    op.create_index("ix_automated_option_marks_ticker", "automated_option_marks", ["ticker"])
    op.create_index("ix_automated_option_marks_strategy_mode", "automated_option_marks", ["strategy_mode"])
    op.create_index("ix_automated_option_marks_mark_type", "automated_option_marks", ["mark_type"])
    op.create_index("ix_automated_option_marks_mark_status", "automated_option_marks", ["mark_status"])
    op.create_index(
        "ix_automated_option_date_status", "automated_option_marks", ["trading_date", "mark_status"]
    )


def downgrade() -> None:
    if "automated_option_marks" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("automated_option_marks")
