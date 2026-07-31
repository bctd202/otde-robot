"""record expiration transitions for Parlay paper positions

Revision ID: 0003_expired_paper_positions
Revises: 0002_parlay_paper_positions
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_expired_paper_positions"
down_revision = "0002_parlay_paper_positions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("parlay_paper_positions")}
    if "expired_at" in columns:
        return
    op.add_column(
        "parlay_paper_positions",
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("parlay_paper_positions")}
    if "expired_at" in columns:
        op.drop_column("parlay_paper_positions", "expired_at")
