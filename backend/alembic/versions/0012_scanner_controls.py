"""add persistent scanner operator controls

Revision ID: 0012_scanner_controls
Revises: 0011_automated_option_marks
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_scanner_controls"
down_revision = "0011_automated_option_marks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("scanner_runtime")}
    if "operator_hold" not in columns:
        op.add_column(
            "scanner_runtime",
            sa.Column("operator_hold", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "control_updated_at" not in columns:
        op.add_column(
            "scanner_runtime",
            sa.Column("control_updated_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("scanner_runtime")}
    if "control_updated_at" in columns:
        op.drop_column("scanner_runtime", "control_updated_at")
    if "operator_hold" in columns:
        op.drop_column("scanner_runtime", "operator_hold")
