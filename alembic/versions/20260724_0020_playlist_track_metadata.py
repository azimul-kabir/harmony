"""Persist playlist track metadata for reliable M3U regeneration.

Revision ID: 20260724_0020
Revises: 20260724_0019
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260724_0020"
down_revision = "20260724_0019"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("title", sa.String()),
    ("artist", sa.String()),
    ("album", sa.String()),
    ("album_artist", sa.String()),
    ("track_number", sa.Integer()),
    ("duration", sa.Float()),
)


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "playlist_tracks" not in inspector.get_table_names():
        return
    existing = {
        column["name"] for column in inspector.get_columns("playlist_tracks")
    }
    with op.batch_alter_table("playlist_tracks") as batch:
        for name, column_type in _COLUMNS:
            if name not in existing:
                batch.add_column(sa.Column(name, column_type, nullable=True))


def downgrade():
    bind = op.get_bind()
    if "playlist_tracks" not in inspect(bind).get_table_names():
        return
    existing = {
        column["name"] for column in inspect(bind).get_columns("playlist_tracks")
    }
    with op.batch_alter_table("playlist_tracks") as batch:
        for name, _ in reversed(_COLUMNS):
            if name in existing:
                batch.drop_column(name)
