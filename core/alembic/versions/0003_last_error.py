"""add last_error column

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plugins", sa.Column("last_error", sa.String(1024), nullable=True))


def downgrade() -> None:
    op.drop_column("plugins", "last_error")
