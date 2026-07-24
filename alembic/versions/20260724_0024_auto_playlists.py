"""Add durable auto-playlist configuration.

Revision ID: 20260724_0024
Revises: 20260724_0023
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260724_0024"
down_revision = "20260724_0023"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "playlists" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("playlists")}
    additions = (
        ("playlist_kind", sa.String(length=20), "source"),
        ("smart_rule", sa.String(length=80), None),
        ("smart_enabled", sa.Boolean(), False),
        ("smart_limit", sa.Integer(), 50),
    )
    for name, column_type, default in additions:
        if name not in columns:
            op.add_column(
                "playlists",
                sa.Column(name, column_type, nullable=True, server_default=None if default is None else str(default)),
            )
    op.execute("UPDATE playlists SET playlist_kind = 'source' WHERE playlist_kind IS NULL")
    op.execute("UPDATE playlists SET smart_enabled = 0 WHERE smart_enabled IS NULL")
    op.execute("UPDATE playlists SET smart_limit = 50 WHERE smart_limit IS NULL")
    indexes = {index["name"] for index in inspect(bind).get_indexes("playlists")}
    for name, columns, unique in (
        ("ix_playlists_playlist_kind", ["playlist_kind"], False),
        ("ix_playlists_smart_rule", ["smart_rule"], True),
    ):
        if name not in indexes:
            op.create_index(name, "playlists", columns, unique=unique)


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "playlists" not in inspector.get_table_names():
        return
    indexes = {index["name"] for index in inspector.get_indexes("playlists")}
    for name in ("ix_playlists_smart_rule", "ix_playlists_playlist_kind"):
        if name in indexes:
            op.drop_index(name, table_name="playlists")
    columns = {column["name"] for column in inspect(bind).get_columns("playlists")}
    with op.batch_alter_table("playlists") as batch:
        for name in ("smart_limit", "smart_enabled", "smart_rule", "playlist_kind"):
            if name in columns:
                batch.drop_column(name)
