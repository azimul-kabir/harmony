"""Persist Navidrome song and playlist reconciliation state.

Revision ID: 20260724_0022
Revises: 20260724_0021
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260724_0022"
down_revision = "20260724_0021"
branch_labels = None
depends_on = None


def _columns(bind, table):
    return {column["name"] for column in inspect(bind).get_columns(table)}


def _indexes(bind, table):
    return {index["name"] for index in inspect(bind).get_indexes(table)}


def upgrade():
    bind = op.get_bind()
    tables = inspect(bind).get_table_names()
    if "songs" in tables:
        columns = _columns(bind, "songs")
        if "navidrome_id" not in columns:
            op.add_column(
                "songs",
                sa.Column("navidrome_id", sa.String(), nullable=True),
            )
        if "ix_songs_navidrome_id" not in _indexes(bind, "songs"):
            op.create_index(
                "ix_songs_navidrome_id",
                "songs",
                ["navidrome_id"],
                unique=True,
            )

    if "playlists" in tables:
        columns = _columns(bind, "playlists")
        additions = (
            ("navidrome_playlist_id", sa.String()),
            ("navidrome_sync_status", sa.String()),
            ("navidrome_synced_track_count", sa.Integer()),
            ("navidrome_sync_error", sa.Text()),
            ("navidrome_synced_at", sa.DateTime()),
        )
        with op.batch_alter_table("playlists") as batch:
            for name, column_type in additions:
                if name not in columns:
                    batch.add_column(
                        sa.Column(name, column_type, nullable=True)
                    )
        if (
            "ix_playlists_navidrome_playlist_id"
            not in _indexes(bind, "playlists")
        ):
            op.create_index(
                "ix_playlists_navidrome_playlist_id",
                "playlists",
                ["navidrome_playlist_id"],
                unique=True,
            )


def downgrade():
    bind = op.get_bind()
    tables = inspect(bind).get_table_names()
    if "playlists" in tables:
        indexes = _indexes(bind, "playlists")
        if "ix_playlists_navidrome_playlist_id" in indexes:
            op.drop_index(
                "ix_playlists_navidrome_playlist_id",
                table_name="playlists",
            )
        columns = _columns(bind, "playlists")
        with op.batch_alter_table("playlists") as batch:
            for name in (
                "navidrome_synced_at",
                "navidrome_sync_error",
                "navidrome_synced_track_count",
                "navidrome_sync_status",
                "navidrome_playlist_id",
            ):
                if name in columns:
                    batch.drop_column(name)
    if "songs" in tables:
        indexes = _indexes(bind, "songs")
        if "ix_songs_navidrome_id" in indexes:
            op.drop_index("ix_songs_navidrome_id", table_name="songs")
        if "navidrome_id" in _columns(bind, "songs"):
            with op.batch_alter_table("songs") as batch:
                batch.drop_column("navidrome_id")
