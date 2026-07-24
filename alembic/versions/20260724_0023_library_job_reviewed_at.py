"""Add acknowledgement state for terminal Library jobs.

Revision ID: 20260724_0023
Revises: 20260724_0022
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260724_0023"
down_revision = "20260724_0022"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "tasks" not in inspector.get_table_names():
        return
    columns = {
        column["name"] for column in inspector.get_columns("tasks")
    }
    if "reviewed_at" not in columns:
        op.add_column(
            "tasks",
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        )
    indexes = {
        index["name"] for index in inspect(bind).get_indexes("tasks")
    }
    if "ix_tasks_reviewed_at" not in indexes:
        op.create_index(
            "ix_tasks_reviewed_at",
            "tasks",
            ["reviewed_at"],
            unique=False,
        )


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "tasks" not in inspector.get_table_names():
        return
    indexes = {
        index["name"] for index in inspector.get_indexes("tasks")
    }
    if "ix_tasks_reviewed_at" in indexes:
        op.drop_index("ix_tasks_reviewed_at", table_name="tasks")
    columns = {
        column["name"] for column in inspect(bind).get_columns("tasks")
    }
    if "reviewed_at" in columns:
        with op.batch_alter_table("tasks") as batch:
            batch.drop_column("reviewed_at")
