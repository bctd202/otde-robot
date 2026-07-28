"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-18
"""
from alembic import op
from app.db.session import Base
from app.db import models  # noqa: F401
revision='0001_initial'; down_revision=None; branch_labels=None; depends_on=None
def upgrade():
    bind = op.get_bind(); Base.metadata.create_all(bind=bind)
def downgrade():
    bind = op.get_bind(); Base.metadata.drop_all(bind=bind)
