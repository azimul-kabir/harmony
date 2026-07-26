"""Add locally indexed lyrics to Songs.

Revision ID: 20260725_0026
Revises: 20260724_0025
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260725_0026"
down_revision = "20260724_0025"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "songs" not in inspect(bind).get_table_names():
        return
    columns = {column["name"] for column in inspect(bind).get_columns("songs")}
    if "lyrics" not in columns:
        op.add_column("songs", sa.Column("lyrics", sa.Text(), nullable=True))
    if "lyrics_source" not in columns:
        op.add_column("songs", sa.Column("lyrics_source", sa.String(32), nullable=True))
    if "lyrics_synced" not in columns:
        op.add_column(
            "songs",
            sa.Column("lyrics_synced", sa.Boolean(), nullable=False, server_default="0"),
        )


def downgrade():
    bind = op.get_bind()
    if "songs" not in inspect(bind).get_table_names():
        return
    columns = {column["name"] for column in inspect(bind).get_columns("songs")}
    with op.batch_alter_table("songs") as batch:
        for name in ("lyrics_synced", "lyrics_source", "lyrics"):
            if name in columns:
                batch.drop_column(name)
