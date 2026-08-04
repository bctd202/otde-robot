"""persist server-derived option contract provenance

Revision ID: 0006_contract_provenance
Revises: 0005_signal_last_evaluated
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_contract_provenance"
down_revision = "0005_signal_last_evaluated"
branch_labels = None
depends_on = None

COMMON = [
    ("provenance_provider", sa.String(32)), ("provenance_data_mode", sa.String(32)),
    ("verification_status", sa.String(32)), ("verification_reason", sa.String(255)),
    ("actionable", sa.Boolean()), ("original_occ_symbol", sa.String(64)),
    ("normalized_option_symbol", sa.String(64)), ("bid_timestamp", sa.DateTime(timezone=True)),
    ("ask_timestamp", sa.DateTime(timezone=True)), ("quote_timestamp", sa.DateTime(timezone=True)),
]
SIGNAL = [("contract_expiration", sa.Date()), ("contract_strike", sa.Float()),
          ("contract_option_type", sa.String(8))]


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table, fields in (("parlay_paper_positions", COMMON), ("signal_performance", COMMON + SIGNAL)):
        existing = {column["name"] for column in inspector.get_columns(table)}
        for name, kind in fields:
            if name not in existing:
                op.add_column(table, sa.Column(name, kind, nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table, fields in (("signal_performance", COMMON + SIGNAL), ("parlay_paper_positions", COMMON)):
        existing = {column["name"] for column in inspector.get_columns(table)}
        for name, _ in reversed(fields):
            if name in existing:
                op.drop_column(table, name)
