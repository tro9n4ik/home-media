"""init

Revision ID: 0001
Revises:
Create Date: 2026-01-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id",            sa.Integer(),     primary_key=True),
        sa.Column("username",      sa.String(64),    nullable=False, unique=True),
        sa.Column("password_hash", sa.String(256),   nullable=False),
        sa.Column("is_admin",      sa.Boolean(),     nullable=False, default=True),
        sa.Column("created_at",    sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_username", "users", ["username"])

    op.create_table(
        "plugins",
        sa.Column("id",             sa.Integer(),    primary_key=True),
        sa.Column("plugin_id",      sa.String(64),   nullable=False, unique=True),
        sa.Column("name",           sa.String(128),  nullable=False),
        sa.Column("version",        sa.String(32),   nullable=False),
        sa.Column("description",    sa.String(512),  nullable=False, default=""),
        sa.Column("manifest",       sa.JSON(),       nullable=False),
        sa.Column("enabled",        sa.Boolean(),    nullable=False, default=True),
        sa.Column("status",         sa.String(32),   nullable=False, default="stopped"),
        sa.Column("container_id",   sa.String(128),  nullable=True),
        sa.Column("container_name", sa.String(128),  nullable=False, default=""),
        sa.Column("data_path",      sa.String(512),  nullable=False, default=""),
        sa.Column("installed_at",   sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at",     sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_plugins_plugin_id", "plugins", ["plugin_id"])

    op.create_table(
        "settings",
        sa.Column("id",        sa.Integer(),   primary_key=True),
        sa.Column("plugin_id", sa.String(64),  nullable=False),
        sa.Column("key",       sa.String(128), nullable=False),
        sa.Column("value",     sa.JSON(),      nullable=True),
        sa.Column("is_secret", sa.Boolean(),   nullable=False, default=False),
        sa.UniqueConstraint("plugin_id", "key", name="uq_settings_plugin_key"),
    )
    op.create_index("ix_settings_plugin_id", "settings", ["plugin_id"])


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_table("plugins")
    op.drop_table("users")
