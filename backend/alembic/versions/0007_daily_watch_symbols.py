"""add daily watch symbols

Revision ID: 0007_daily_watch_symbols
Revises: 0006_contract_provenance
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_daily_watch_symbols"
down_revision = "0006_contract_provenance"
branch_labels = None
depends_on = None

def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "daily_watch_symbols" not in inspector.get_table_names():
        op.create_table("daily_watch_symbols",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("trading_date", sa.Date(), nullable=False),
            sa.Column("symbol", sa.String(12), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("trading_date", "symbol", name="uq_daily_watch_date_symbol"))
        op.create_index("ix_daily_watch_symbols_trading_date", "daily_watch_symbols", ["trading_date"])

def downgrade() -> None:
    if "daily_watch_symbols" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_index("ix_daily_watch_symbols_trading_date", table_name="daily_watch_symbols")
        op.drop_table("daily_watch_symbols")
