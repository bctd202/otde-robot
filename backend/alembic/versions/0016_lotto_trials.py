"""Separate forward lotto experiments; no historical imports or repricing."""
from alembic import op
import sqlalchemy as sa

revision = "0016_lotto_trials"
down_revision = "0015_forward_equity"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("lottery_quote_snapshots")}
    tables = set(inspector.get_table_names())
    for name, kind in (("received_at", sa.DateTime(timezone=True)), ("provider", sa.String(32)),
                       ("data_mode", sa.String(16))):
        if name not in columns:
            op.add_column("lottery_quote_snapshots", sa.Column(name, kind, nullable=True))
    if "lotto_trial_accounts" not in tables:
        op.create_table("lotto_trial_accounts", sa.Column("key", sa.String(48), primary_key=True),
            sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False), sa.Column("policy", sa.JSON(), nullable=False))
    if "lotto_trial_positions" not in tables:
        op.create_table("lotto_trial_positions", sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("account_key", sa.String(48), sa.ForeignKey("lotto_trial_accounts.key"), nullable=False),
            sa.Column("tracker_id", sa.String(36), sa.ForeignKey("lottery_trackers.id"), nullable=False),
            sa.Column("status", sa.String(24), nullable=False), sa.Column("detail", sa.JSON(), nullable=False),
            sa.UniqueConstraint("account_key", "tracker_id", name="uq_lotto_trial_tracker"))
        op.create_index("ix_lotto_trial_positions_account_key", "lotto_trial_positions", ["account_key"])
    if "lotto_trial_events" not in tables:
        op.create_table("lotto_trial_events", sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("account_key", sa.String(48), sa.ForeignKey("lotto_trial_accounts.key"), nullable=False),
            sa.Column("event_key", sa.String(120), nullable=False),
            sa.Column("at", sa.DateTime(timezone=True), nullable=False), sa.Column("kind", sa.String(24), nullable=False),
            sa.Column("settled", sa.Integer(), nullable=False), sa.Column("unsettled", sa.Integer(), nullable=False),
            sa.Column("realized", sa.Integer(), nullable=False), sa.Column("detail", sa.JSON(), nullable=False),
            sa.UniqueConstraint("account_key", "event_key", name="uq_lotto_trial_event"))
        op.create_index("ix_lotto_trial_events_account_key", "lotto_trial_events", ["account_key"])
        op.create_index("ix_lotto_trial_events_at", "lotto_trial_events", ["at"])


def downgrade():
    op.drop_table("lotto_trial_events")
    op.drop_table("lotto_trial_positions")
    op.drop_table("lotto_trial_accounts")
    with op.batch_alter_table("lottery_quote_snapshots") as batch:
        for name in ("received_at", "provider", "data_mode"):
            batch.drop_column(name)
