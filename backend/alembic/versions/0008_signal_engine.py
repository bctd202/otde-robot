"""add durable signal engine state

Revision ID: 0008_signal_engine
Revises: 0007_daily_watch_symbols
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_signal_engine"
down_revision = "0007_daily_watch_symbols"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "signal_scans" not in tables:
        op.create_table("signal_scans",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("trading_date", sa.Date(), nullable=False),
            sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("evaluation_candle_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("provider_status", sa.JSON(), nullable=False),
            sa.Column("universe", sa.JSON(), nullable=False),
            sa.Column("candidates", sa.JSON(), nullable=False))
        op.create_index("ix_signal_scans_trading_date", "signal_scans", ["trading_date"])
        op.create_index("ix_signal_scans_scanned_at", "signal_scans", ["scanned_at"])
        op.create_index("ix_signal_scans_evaluation_candle_at", "signal_scans", ["evaluation_candle_at"])
    if "signal_lifecycles" not in tables:
        op.create_table("signal_lifecycles",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("symbol", sa.String(12), nullable=False),
            sa.Column("direction", sa.String(8), nullable=False),
            sa.Column("trading_date", sa.Date(), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("evaluation_candle_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("reason", sa.String(255), nullable=False),
            sa.Column("candidate_snapshot", sa.JSON(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
        op.create_index("ix_signal_lifecycles_symbol", "signal_lifecycles", ["symbol"])
        op.create_index("ix_signal_lifecycles_trading_date", "signal_lifecycles", ["trading_date"])
        op.create_index("ix_signal_lifecycles_status", "signal_lifecycles", ["status"])
        op.create_index("ix_signal_lifecycle_active", "signal_lifecycles", ["trading_date", "symbol", "status"])
    if "signal_alerts" not in tables:
        op.create_table("signal_alerts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("dedupe_key", sa.String(180), nullable=False, unique=True),
            sa.Column("lifecycle_id", sa.String(36), sa.ForeignKey("signal_lifecycles.id"), nullable=True),
            sa.Column("symbol", sa.String(12), nullable=False),
            sa.Column("event_type", sa.String(32), nullable=False),
            sa.Column("message", sa.String(255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("acknowledged", sa.Boolean(), nullable=False, server_default=sa.false()))
        op.create_index("ix_signal_alerts_symbol", "signal_alerts", ["symbol"])
        op.create_index("ix_signal_alerts_event_type", "signal_alerts", ["event_type"])
        op.create_index("ix_signal_alerts_created_at", "signal_alerts", ["created_at"])
    if "scanner_runtime" not in tables:
        op.create_table("scanner_runtime",
            sa.Column("key", sa.String(32), primary_key=True),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("last_scan_started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_scan_completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_evaluation_candle_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("next_evaluation_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_error", sa.String(500), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "scanner_runtime" in tables:
        op.drop_table("scanner_runtime")
    if "signal_alerts" in tables:
        op.drop_index("ix_signal_alerts_created_at", table_name="signal_alerts")
        op.drop_index("ix_signal_alerts_event_type", table_name="signal_alerts")
        op.drop_index("ix_signal_alerts_symbol", table_name="signal_alerts")
        op.drop_table("signal_alerts")
    if "signal_lifecycles" in tables:
        op.drop_index("ix_signal_lifecycle_active", table_name="signal_lifecycles")
        op.drop_index("ix_signal_lifecycles_status", table_name="signal_lifecycles")
        op.drop_index("ix_signal_lifecycles_trading_date", table_name="signal_lifecycles")
        op.drop_index("ix_signal_lifecycles_symbol", table_name="signal_lifecycles")
        op.drop_table("signal_lifecycles")
    if "signal_scans" in tables:
        op.drop_index("ix_signal_scans_evaluation_candle_at", table_name="signal_scans")
        op.drop_index("ix_signal_scans_scanned_at", table_name="signal_scans")
        op.drop_index("ix_signal_scans_trading_date", table_name="signal_scans")
        op.drop_table("signal_scans")
