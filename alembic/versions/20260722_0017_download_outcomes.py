"""add structured download outcomes

Revision ID: 20260722_0017
Revises: 20260722_0016
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260722_0017"
down_revision = "20260722_0016"
branch_labels = None
depends_on = None


def upgrade():
    inspector = inspect(op.get_bind())
    if "download_jobs" not in inspector.get_table_names():
        return
    if "reason_code" in {column["name"] for column in inspector.get_columns("download_jobs")}:
        return
    op.add_column("download_jobs", sa.Column("reason_code", sa.String(), nullable=True))
    op.create_index("ix_download_jobs_reason_code", "download_jobs", ["reason_code"])
    op.add_column("download_jobs", sa.Column("reason_message", sa.String(), nullable=True))
    op.add_column("download_jobs", sa.Column("failure_stage", sa.String(), nullable=True))
    op.add_column("download_jobs", sa.Column("provider", sa.String(), nullable=True))
    op.add_column("download_jobs", sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("download_jobs", sa.Column("technical_detail", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("download_jobs", "technical_detail")
    op.drop_column("download_jobs", "retryable")
    op.drop_column("download_jobs", "provider")
    op.drop_column("download_jobs", "failure_stage")
    op.drop_column("download_jobs", "reason_message")
    op.drop_index("ix_download_jobs_reason_code", table_name="download_jobs")
    op.drop_column("download_jobs", "reason_code")
