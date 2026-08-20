"""refactor plugin runtime state

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем runtime-поля
    op.add_column("plugins", sa.Column("assigned_port", sa.Integer(),            nullable=True))
    op.add_column("plugins", sa.Column("pid",           sa.Integer(),            nullable=True))
    op.add_column("plugins", sa.Column("started_at",    sa.DateTime(timezone=True), nullable=True))
    op.add_column("plugins", sa.Column("health_at",     sa.DateTime(timezone=True), nullable=True))

    # Убираем docker-остатки
    op.drop_column("plugins", "container_id")
    op.drop_column("plugins", "container_name")

    # Обновляем статус по умолчанию
    op.execute("UPDATE plugins SET status = 'installed' WHERE status = 'stopped'")


def downgrade() -> None:
    op.drop_column("plugins", "assigned_port")
    op.drop_column("plugins", "pid")
    op.drop_column("plugins", "started_at")
    op.drop_column("plugins", "health_at")
    op.add_column("plugins", sa.Column("container_id",   sa.String(128), nullable=True))
    op.add_column("plugins", sa.Column("container_name", sa.String(128), nullable=False, server_default=""))
