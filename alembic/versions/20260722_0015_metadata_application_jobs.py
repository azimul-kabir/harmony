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
    bind = op.get_bind()
    if "metadata_application_locks" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "metadata_application_locks",
            sa.Column("song_id", sa.Integer(), primary_key=True),
            sa.Column(
                "task_id",
                sa.Integer(),
                sa.ForeignKey("tasks.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    existing_indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes("metadata_application_locks")
    }
    if "ix_metadata_application_locks_task_id" not in existing_indexes:
        op.create_index(
            "ix_metadata_application_locks_task_id",
            "metadata_application_locks",
            ["task_id"],
        )


def downgrade() -> None:
    op.drop_table("metadata_application_locks")
