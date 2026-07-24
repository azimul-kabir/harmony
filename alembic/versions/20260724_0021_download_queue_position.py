"""Persist the original playlist position on download jobs.

Revision ID: 20260724_0021
Revises: 20260724_0020
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260724_0021"
down_revision = "20260724_0020"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "download_jobs" not in inspector.get_table_names():
        return
    columns = {
        column["name"] for column in inspector.get_columns("download_jobs")
    }
    if "queue_position" not in columns:
        op.add_column(
            "download_jobs",
            sa.Column("queue_position", sa.Integer(), nullable=True),
        )


def downgrade():
    bind = op.get_bind()
    if "download_jobs" not in inspect(bind).get_table_names():
        return
    columns = {
        column["name"] for column in inspect(bind).get_columns("download_jobs")
    }
    if "queue_position" in columns:
        with op.batch_alter_table("download_jobs") as batch:
            batch.drop_column("queue_position")
