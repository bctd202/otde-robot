"""expand paper positions for Parlay snapshots

Revision ID: 0002_parlay_paper_positions
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_parlay_paper_positions"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "parlay_paper_positions" in inspector.get_table_names():
        return
    op.create_table(
        "parlay_paper_positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(12), nullable=False),
        sa.Column("option_symbol", sa.String(64), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("expiration", sa.Date(), nullable=False),
        sa.Column("strike", sa.Float(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("entry_option_price", sa.Float(), nullable=False),
        sa.Column("entry_underlying_price", sa.Float(), nullable=False),
        sa.Column("total_debit", sa.Float(), nullable=False),
        sa.Column("underlying_trigger", sa.Float(), nullable=False),
        sa.Column("underlying_invalidation", sa.Float(), nullable=False),
        sa.Column("first_underlying_target", sa.Float(), nullable=False),
        sa.Column("stretch_underlying_target", sa.Float(), nullable=False),
        sa.Column("first_option_target", sa.Float(), nullable=False),
        sa.Column("stretch_option_target", sa.Float(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("score_label", sa.String(32), nullable=False),
        sa.Column("entry_reasons", sa.JSON(), nullable=False),
        sa.Column("provider_mode", sa.String(32), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("exit_option_price", sa.Float()),
        sa.Column("exit_underlying_price", sa.Float()),
        sa.Column("exit_reason", sa.String(255)),
        sa.Column("lifecycle_status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("last_option_price", sa.Float()),
        sa.Column("last_underlying_price", sa.Float()),
        sa.Column("last_marked_at", sa.DateTime(timezone=True)),
        sa.Column("data_freshness", sa.String(32), nullable=False, server_default="current"),
    )
    op.create_index("ix_parlay_paper_positions_symbol", "parlay_paper_positions", ["symbol"])
    op.create_index("ix_parlay_paper_positions_option_symbol", "parlay_paper_positions", ["option_symbol"])
    op.create_index("ix_parlay_paper_positions_lifecycle_status", "parlay_paper_positions", ["lifecycle_status"])


def downgrade() -> None:
    op.drop_table("parlay_paper_positions")
