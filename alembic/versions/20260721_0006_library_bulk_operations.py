"""Add durable Library bulk operations."""

from alembic import op
import sqlalchemy as sa

revision = "20260721_0006"
down_revision = "20260721_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "tasks" not in inspector.get_table_names():
        op.create_table(
            "tasks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("spotify_url", sa.String(), nullable=False),
            sa.Column("source_id", sa.Integer(), nullable=True),
            sa.Column("task_type", sa.String(), nullable=False, server_default="track_download"),
            sa.Column("status", sa.String(), nullable=False, server_default="queued"),
            sa.Column("total_items", sa.Integer(), server_default="0"),
            sa.Column("completed_items", sa.Integer(), server_default="0"),
            sa.Column("skipped_items", sa.Integer(), server_default="0"),
            sa.Column("failed_items", sa.Integer(), server_default="0"),
            sa.Column("current_item", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("operation_payload", sa.Text(), nullable=True),
            sa.Column("output_path", sa.String(), nullable=True),
        )
        op.create_index("ix_tasks_source_id", "tasks", ["source_id"])
        task_columns = {"operation_payload", "output_path"}
    else:
        task_columns = {column["name"] for column in inspector.get_columns("tasks")}
    with op.batch_alter_table("tasks") as batch:
        if "operation_payload" not in task_columns:
            batch.add_column(sa.Column("operation_payload", sa.Text(), nullable=True))
        if "output_path" not in task_columns:
            batch.add_column(sa.Column("output_path", sa.String(), nullable=True))

    if "bulk_operation_items" not in inspector.get_table_names():
        op.create_table(
            "bulk_operation_items",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
            sa.Column("song_id", sa.Integer(), sa.ForeignKey("songs.id"), nullable=True),
            sa.Column("original_path", sa.String(), nullable=False),
            sa.Column("result_path", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="queued"),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_bulk_operation_items_task_id", "bulk_operation_items", ["task_id"])
        op.create_index("ix_bulk_operation_items_song_id", "bulk_operation_items", ["song_id"])
        op.create_index("ix_bulk_operation_items_status", "bulk_operation_items", ["status"])


def downgrade() -> None:
    pass
