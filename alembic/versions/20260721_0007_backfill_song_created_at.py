"""Backfill creation timestamps required by the Library Song response."""

from alembic import op
import sqlalchemy as sa


revision = "20260721_0007"
down_revision = "20260721_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if "songs" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("songs")}
    if "created_at" not in columns:
        op.add_column("songs", sa.Column("created_at", sa.DateTime(), nullable=True))
        columns.add("created_at")

    fallbacks = ["last_indexed_at", "last_modified"]
    if "modified_time" in columns:
        fallbacks.append("datetime(modified_time, 'unixepoch')")
    fallbacks.append("CURRENT_TIMESTAMP")
    op.execute(
        "UPDATE songs SET created_at = COALESCE("
        + ", ".join(fallbacks)
        + ") WHERE created_at IS NULL"
    )


def downgrade() -> None:
    # Creation timestamps are preserved to avoid destructive SQLite table rebuilds.
    pass
