"""Persist bounded download retry state."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260812_0031"
down_revision = "20260730_0030"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "download_jobs" not in inspect(bind).get_table_names():
        return
    columns = {column["name"] for column in inspect(bind).get_columns("download_jobs")}
    indexes = {index["name"] for index in inspect(bind).get_indexes("download_jobs")}
    with op.batch_alter_table("download_jobs") as batch:
        if "attempt_count" not in columns:
            batch.add_column(
                sa.Column(
                    "attempt_count", sa.Integer(), nullable=False, server_default="0"
                )
            )
        if "next_attempt_at" not in columns:
            batch.add_column(sa.Column("next_attempt_at", sa.DateTime(), nullable=True))
        if "ix_download_jobs_next_attempt_at" not in indexes:
            batch.create_index(
                "ix_download_jobs_next_attempt_at", ["next_attempt_at"], unique=False
            )


def downgrade():
    bind = op.get_bind()
    if "download_jobs" not in inspect(bind).get_table_names():
        return
    columns = {column["name"] for column in inspect(bind).get_columns("download_jobs")}
    indexes = {index["name"] for index in inspect(bind).get_indexes("download_jobs")}
    with op.batch_alter_table("download_jobs") as batch:
        if "ix_download_jobs_next_attempt_at" in indexes:
            batch.drop_index("ix_download_jobs_next_attempt_at")
        if "next_attempt_at" in columns:
            batch.drop_column("next_attempt_at")
        if "attempt_count" in columns:
            batch.drop_column("attempt_count")
