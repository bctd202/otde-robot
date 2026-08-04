"""persist live signal evaluation cursor

Revision ID: 0005_signal_last_evaluated
Revises: 0004_signal_performance
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_signal_last_evaluated"
down_revision = "0004_signal_performance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("signal_performance")}
    if "last_evaluated_at" not in columns:
        op.add_column("signal_performance", sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True))
        op.execute("UPDATE signal_performance SET last_evaluated_at = COALESCE(updated_at, triggered_at)")


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("signal_performance")}
    if "last_evaluated_at" in columns:
        op.drop_column("signal_performance", "last_evaluated_at")
