"""Persist source duration on download jobs.

Revision ID: 20260729_0029
Revises: 20260729_0028
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260729_0029"
down_revision = "20260729_0028"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "download_jobs" not in inspector.get_table_names():
        return
    if "duration" in {
        column["name"] for column in inspector.get_columns("download_jobs")
    }:
        return
    op.add_column(
        "download_jobs", sa.Column("duration", sa.Float(), nullable=True)
    )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "download_jobs" not in inspector.get_table_names():
        return
    if "duration" in {
        column["name"] for column in inspector.get_columns("download_jobs")
    }:
        op.drop_column("download_jobs", "duration")
