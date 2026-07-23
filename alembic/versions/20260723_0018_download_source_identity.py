"""add provider-neutral download source identity

Revision ID: 20260723_0018
Revises: 20260722_0017
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260723_0018"
down_revision = "20260722_0017"
branch_labels = None
depends_on = None

def upgrade():
    inspector = inspect(op.get_bind())
    if "download_jobs" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("download_jobs")}
    with op.batch_alter_table("download_jobs") as batch:
        if "source_provider" not in columns:
            batch.add_column(sa.Column("source_provider", sa.String(length=80), nullable=False, server_default="spotify"))
        if "source_item_id" not in columns:
            batch.add_column(sa.Column("source_item_id", sa.String(length=255), nullable=True))
    indexes = {index["name"] for index in inspect(op.get_bind()).get_indexes("download_jobs")}
    if "ix_download_jobs_source_provider" not in indexes:
        op.create_index("ix_download_jobs_source_provider", "download_jobs", ["source_provider"])
    if "ix_download_jobs_source_item_id" not in indexes:
        op.create_index("ix_download_jobs_source_item_id", "download_jobs", ["source_item_id"])

def downgrade():
    op.drop_index("ix_download_jobs_source_item_id", table_name="download_jobs")
    op.drop_index("ix_download_jobs_source_provider", table_name="download_jobs")
    with op.batch_alter_table("download_jobs") as batch:
        batch.drop_column("source_item_id")
        batch.drop_column("source_provider")
