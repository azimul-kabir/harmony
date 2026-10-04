"""Add schedule run history.

Revision ID: 20260825_0033
Revises: 20260812_0032
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260825_0033"
down_revision = "20260812_0032"
branch_labels = None
depends_on = None


def upgrade():
    if "schedule_runs" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "schedule_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("delay_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["sync_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_schedule_runs_source_id", "schedule_runs", ["source_id"])
    op.create_index("ix_schedule_runs_task_id", "schedule_runs", ["task_id"])
    op.create_index("ix_schedule_runs_trigger", "schedule_runs", ["trigger"])
    op.create_index("ix_schedule_runs_status", "schedule_runs", ["status"])


def downgrade():
    if "schedule_runs" in inspect(op.get_bind()).get_table_names():
        op.drop_table("schedule_runs")
