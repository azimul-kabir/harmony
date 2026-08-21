"""Add an explicitly approved manual fallback URL to download jobs."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260812_0032"
down_revision = "20260812_0031"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "download_jobs" not in inspect(bind).get_table_names():
        return
    columns = {column["name"] for column in inspect(bind).get_columns("download_jobs")}
    if "manual_fallback_url" not in columns:
        with op.batch_alter_table("download_jobs") as batch:
            batch.add_column(sa.Column("manual_fallback_url", sa.String(), nullable=True))


def downgrade():
    bind = op.get_bind()
    if "download_jobs" not in inspect(bind).get_table_names():
        return
    columns = {column["name"] for column in inspect(bind).get_columns("download_jobs")}
    if "manual_fallback_url" in columns:
        with op.batch_alter_table("download_jobs") as batch:
            batch.drop_column("manual_fallback_url")
