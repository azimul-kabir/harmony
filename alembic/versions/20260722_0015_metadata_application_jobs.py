"""Add per-Song reservations for durable metadata application jobs.

Revision ID: 20260722_0015
Revises: 20260722_0014
"""
from alembic import op
import sqlalchemy as sa

revision = "20260722_0015"
down_revision = "20260722_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "metadata_application_locks" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table("metadata_application_locks",
        sa.Column("song_id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_metadata_application_locks_task_id", "metadata_application_locks", ["task_id"])


def downgrade() -> None:
    op.drop_table("metadata_application_locks")
