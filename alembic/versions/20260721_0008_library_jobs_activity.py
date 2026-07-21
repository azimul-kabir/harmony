"""Add persistent library job diagnostics and recovery metadata."""
from alembic import op
import sqlalchemy as sa

revision = "20260721_0008"
down_revision = "20260721_0007"
branch_labels = None
depends_on = None

def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("tasks")}
    additions = [
        ("error_summary", sa.String(500)), ("error_code", sa.String(80)),
        ("cancellation_requested_at", sa.DateTime()), ("initiated_by", sa.String(120)),
        ("resource_key", sa.String(160)), ("resumable", sa.Boolean(),),
        ("recovery_metadata", sa.Text()),
    ]
    with op.batch_alter_table("tasks") as batch:
        for name, type_ in additions:
            if name not in columns:
                batch.add_column(sa.Column(name, type_, nullable=True))
    op.execute("UPDATE tasks SET resumable = 0 WHERE resumable IS NULL")
    op.create_index("ix_tasks_resource_key", "tasks", ["resource_key"], if_not_exists=True)
    op.create_index(
        "uq_tasks_active_resource_key",
        "tasks",
        ["resource_key"],
        unique=True,
        sqlite_where=sa.text("resource_key IS NOT NULL AND status IN ('queued', 'running', 'cancelling')"),
        if_not_exists=True,
    )
    if "task_item_failures" not in inspector.get_table_names():
        op.create_table("task_item_failures", sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
            sa.Column("item_description", sa.String(500), nullable=False), sa.Column("error_code", sa.String(80), nullable=False),
            sa.Column("message", sa.String(500), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
        op.create_index("ix_task_item_failures_task_id", "task_item_failures", ["task_id"])

def downgrade() -> None:
    op.drop_table("task_item_failures")
    op.drop_index("uq_tasks_active_resource_key", table_name="tasks")
    op.drop_index("ix_tasks_resource_key", table_name="tasks")
