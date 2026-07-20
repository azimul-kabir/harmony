"""Add the persistent Library Foundation index fields."""

from alembic import op
import sqlalchemy as sa

revision = "20260721_0001"
down_revision = None
branch_labels = None
depends_on = None


COLUMNS = {
    "bitrate": sa.Column("bitrate", sa.Integer(), nullable=True),
    "codec": sa.Column("codec", sa.String(), nullable=True),
    "sample_rate": sa.Column("sample_rate", sa.Integer(), nullable=True),
    "last_modified": sa.Column("last_modified", sa.DateTime(), nullable=True),
    "last_indexed_at": sa.Column("last_indexed_at", sa.DateTime(), nullable=True),
    "metadata_hash": sa.Column("metadata_hash", sa.String(), nullable=True),
    "artwork_status": sa.Column(
        "artwork_status",
        sa.String(),
        nullable=False,
        server_default="missing",
    ),
    "availability_status": sa.Column(
        "availability_status",
        sa.String(),
        nullable=False,
        server_default="available",
    ),
    "download_source": sa.Column(
        "download_source",
        sa.String(),
        nullable=False,
        server_default="filesystem",
    ),
    "musicbrainz_recording_id": sa.Column(
        "musicbrainz_recording_id",
        sa.String(),
        nullable=True,
    ),
}


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing = {column["name"] for column in inspector.get_columns("songs")}

    for name, column in COLUMNS.items():
        if name not in existing:
            op.add_column("songs", column)

    indexes = {index["name"] for index in sa.inspect(connection).get_indexes("songs")}
    if "ix_songs_availability_status" not in indexes:
        op.create_index(
            "ix_songs_availability_status",
            "songs",
            ["availability_status"],
        )
    if "ix_songs_musicbrainz_recording_id" not in indexes:
        op.create_index(
            "ix_songs_musicbrainz_recording_id",
            "songs",
            ["musicbrainz_recording_id"],
        )


def downgrade() -> None:
    # SQLite cannot safely remove these columns without recreating songs. The
    # foundation migration is intentionally additive and preserves library data.
    pass
