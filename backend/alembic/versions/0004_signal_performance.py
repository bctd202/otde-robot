"""add signal performance ledger and backtest runs"""
from alembic import op
import sqlalchemy as sa
revision="0004_signal_performance"; down_revision="0003_expired_paper_positions"; branch_labels=None; depends_on=None

def upgrade():
    inspector=sa.inspect(op.get_bind())
    if "live_wait_candidates" not in inspector.get_table_names():
        op.create_table("live_wait_candidates",sa.Column("key",sa.String(160),primary_key=True),sa.Column("ticker",sa.String(12),nullable=False),sa.Column("direction",sa.String(4),nullable=False),sa.Column("first_seen_at",sa.DateTime(timezone=True),nullable=False),sa.Column("condition_snapshot",sa.JSON(),nullable=False))
        op.create_index("ix_live_wait_candidates_ticker","live_wait_candidates",["ticker"])
    if "backtest_runs" not in inspector.get_table_names():
        op.create_table("backtest_runs",sa.Column("id",sa.String(36),primary_key=True),sa.Column("requested_start",sa.Date(),nullable=False),sa.Column("requested_end",sa.Date(),nullable=False),sa.Column("actual_start",sa.Date()),sa.Column("actual_end",sa.Date()),sa.Column("tickers",sa.JSON(),nullable=False),sa.Column("strategy_snapshot",sa.JSON(),nullable=False),sa.Column("status",sa.String(16),nullable=False),sa.Column("warnings",sa.JSON(),nullable=False),sa.Column("failures",sa.JSON(),nullable=False),sa.Column("started_at",sa.DateTime(timezone=True),nullable=False),sa.Column("completed_at",sa.DateTime(timezone=True)))
        op.create_index("ix_backtest_runs_status","backtest_runs",["status"])
    if "signal_performance" not in inspector.get_table_names():
        op.create_table("signal_performance",sa.Column("signal_id",sa.String(36),primary_key=True),sa.Column("source",sa.String(12),nullable=False),sa.Column("dedupe_key",sa.String(160),nullable=False),sa.Column("backtest_run_id",sa.String(36),sa.ForeignKey("backtest_runs.id")),sa.Column("ticker",sa.String(12),nullable=False),sa.Column("direction",sa.String(4),nullable=False),sa.Column("backend_status",sa.String(16),nullable=False),sa.Column("setup_type",sa.String(64),nullable=False),sa.Column("strategy_version",sa.String(32),nullable=False),sa.Column("strategy_snapshot",sa.JSON(),nullable=False),sa.Column("condition_snapshot",sa.JSON(),nullable=False),sa.Column("trading_date",sa.Date(),nullable=False),sa.Column("first_wait_at",sa.DateTime(timezone=True)),sa.Column("triggered_at",sa.DateTime(timezone=True),nullable=False),sa.Column("entry_price",sa.Float(),nullable=False),sa.Column("stop_price",sa.Float(),nullable=False),sa.Column("target_price",sa.Float(),nullable=False),sa.Column("exit_at",sa.DateTime(timezone=True)),sa.Column("exit_price",sa.Float()),sa.Column("exit_reason",sa.String(16),nullable=False),sa.Column("result_r",sa.Float()),sa.Column("mfe_r",sa.Float(),nullable=False),sa.Column("mae_r",sa.Float(),nullable=False),sa.Column("duration_minutes",sa.Integer()),sa.Column("score",sa.Float(),nullable=False),sa.Column("user_entered",sa.Boolean(),nullable=False),sa.Column("paper_position_id",sa.Integer(),sa.ForeignKey("parlay_paper_positions.id")),sa.Column("option_snapshot",sa.JSON()),sa.Column("conservative_same_candle",sa.Boolean(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint("source","dedupe_key",name="uq_signal_performance_source_key"))
        op.create_index("ix_signal_performance_filters","signal_performance",["source","trading_date","ticker","exit_reason"])
        for c in ("backtest_run_id","ticker","trading_date","triggered_at","exit_reason","user_entered"): op.create_index(f"ix_signal_performance_{c}","signal_performance",[c])

def downgrade():
    op.drop_table("signal_performance"); op.drop_table("backtest_runs"); op.drop_table("live_wait_candidates")
