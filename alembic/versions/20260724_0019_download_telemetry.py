"""Add persisted download heartbeat and telemetry.

Revision ID: 20260724_0019
Revises: 20260723_0018
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260724_0019"
down_revision = "20260723_0018"
branch_labels = None
depends_on = None


_COLUMNS = (
    # These fields predate the Alembic chain and can be absent from legacy
    # databases that were upgraded rather than created from current metadata.
    ("cover_url", sa.String()),
    ("error_message", sa.String()),
    ("source_url", sa.String()),
    ("updated_at", sa.DateTime()),
    ("pipeline_stage", sa.String(length=40)),
    ("progress_percent", sa.Integer()),
    ("heartbeat_at", sa.DateTime()),
    ("worker_name", sa.String(length=80)),
    ("bytes_downloaded", sa.Integer()),
    ("bytes_total", sa.Integer()),
    ("transfer_rate_bps", sa.Integer()),
    ("eta_seconds", sa.Integer()),
)


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "songs" in inspector.get_table_names():
        song_columns = {
            column["name"] for column in inspector.get_columns("songs")
        }
        if "cover_url" not in song_columns:
            op.add_column(
                "songs", sa.Column("cover_url", sa.String(), nullable=True)
            )
    if "download_jobs" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("download_jobs")}
    with op.batch_alter_table("download_jobs") as batch:
        for name, column_type in _COLUMNS:
            if name not in existing:
                batch.add_column(sa.Column(name, column_type, nullable=True))
    timestamp_sources = [
        name
        for name in ("completed_at", "started_at", "created_at")
        if name in existing
    ]
    if timestamp_sources:
        bind.execute(
            sa.text(
                "UPDATE download_jobs SET updated_at = "
                f"COALESCE(updated_at, {', '.join(timestamp_sources)}) "
                "WHERE updated_at IS NULL"
            )
        )
    indexes = {index["name"] for index in inspect(bind).get_indexes("download_jobs")}
    if "ix_download_jobs_heartbeat_at" not in indexes:
        op.create_index("ix_download_jobs_heartbeat_at", "download_jobs", ["heartbeat_at"])


def downgrade():
    bind = op.get_bind()
    if "download_jobs" not in inspect(bind).get_table_names():
        return
    indexes = {index["name"] for index in inspect(bind).get_indexes("download_jobs")}
    if "ix_download_jobs_heartbeat_at" in indexes:
        op.drop_index("ix_download_jobs_heartbeat_at", table_name="download_jobs")
    existing = {column["name"] for column in inspect(bind).get_columns("download_jobs")}
    with op.batch_alter_table("download_jobs") as batch:
        for name, _ in reversed(_COLUMNS):
            if name in existing:
                batch.drop_column(name)
