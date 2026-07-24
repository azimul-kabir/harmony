"""Add per-source automatic sync scheduling.

Revision ID: 20260724_0025
Revises: 20260724_0024
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260724_0025"
down_revision = "20260724_0024"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "sync_sources" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("sync_sources")}
    for name, column_type, default in (
        ("auto_sync_enabled", sa.Boolean(), "0"),
        ("auto_sync_interval_minutes", sa.Integer(), "360"),
        ("auto_sync_last_attempt_at", sa.DateTime(), None),
    ):
        if name not in columns:
            op.add_column(
                "sync_sources",
                sa.Column(name, column_type, nullable=True, server_default=default),
            )
    op.execute("UPDATE sync_sources SET auto_sync_enabled = 0 WHERE auto_sync_enabled IS NULL")
    op.execute("UPDATE sync_sources SET auto_sync_interval_minutes = 360 WHERE auto_sync_interval_minutes IS NULL")
    indexes = {index["name"] for index in inspect(bind).get_indexes("sync_sources")}
    if "ix_sync_sources_auto_sync_enabled" not in indexes:
        op.create_index("ix_sync_sources_auto_sync_enabled", "sync_sources", ["auto_sync_enabled"])


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "sync_sources" not in inspector.get_table_names():
        return
    indexes = {index["name"] for index in inspector.get_indexes("sync_sources")}
    if "ix_sync_sources_auto_sync_enabled" in indexes:
        op.drop_index("ix_sync_sources_auto_sync_enabled", table_name="sync_sources")
    columns = {column["name"] for column in inspect(bind).get_columns("sync_sources")}
    with op.batch_alter_table("sync_sources") as batch:
        for name in ("auto_sync_last_attempt_at", "auto_sync_interval_minutes", "auto_sync_enabled"):
            if name in columns:
                batch.drop_column(name)
