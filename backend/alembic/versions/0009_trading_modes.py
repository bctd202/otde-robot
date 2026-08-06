"""add trading modes and normalized performance

Revision ID: 0009_trading_modes
Revises: 0008_signal_engine
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_trading_modes"
down_revision = "0008_signal_engine"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("signal_lifecycles", "parlay_paper_positions", "live_wait_candidates", "signal_performance"):
        if table not in tables:
            continue
        columns = _columns(table)
        if "strategy_mode" not in columns:
            op.add_column(table, sa.Column("strategy_mode", sa.String(32), nullable=False,
                                          server_default="ONE_MIN_0DTE"))
        if table != "signal_performance" and "strategy_version" not in columns:
            op.add_column(table, sa.Column("strategy_version", sa.String(40), nullable=False,
                                          server_default="parlay-v1"))
        index_name = f"ix_{table}_strategy_mode"
        indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}
        if index_name not in indexes:
            op.create_index(index_name, table, ["strategy_mode"])
    if "signal_lifecycles" in tables:
        indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("signal_lifecycles")}
        if "ix_signal_lifecycle_strategy_active" not in indexes:
            op.create_index("ix_signal_lifecycle_strategy_active", "signal_lifecycles",
                            ["trading_date", "symbol", "strategy_mode", "status"])
    if "signal_performance" in tables and "result_return_pct" not in _columns("signal_performance"):
        op.add_column("signal_performance", sa.Column("result_return_pct", sa.Float(), nullable=True))


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "signal_performance" in tables and "result_return_pct" in _columns("signal_performance"):
        op.drop_column("signal_performance", "result_return_pct")
    for table in ("signal_performance", "live_wait_candidates", "parlay_paper_positions", "signal_lifecycles"):
        if table not in tables:
            continue
        columns = _columns(table)
        index_name = f"ix_{table}_strategy_mode"
        indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}
        if table == "signal_lifecycles" and "ix_signal_lifecycle_strategy_active" in indexes:
            op.drop_index("ix_signal_lifecycle_strategy_active", table_name=table)
        if index_name in indexes:
            op.drop_index(index_name, table_name=table)
        if table != "signal_performance" and "strategy_version" in columns:
            op.drop_column(table, "strategy_version")
        if "strategy_mode" in columns:
            op.drop_column(table, "strategy_mode")
