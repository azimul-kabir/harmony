"""Add indexes for composable Library sorting and filtering."""

from alembic import op
import sqlalchemy as sa

revision = "20260721_0004"
down_revision = "20260721_0003"
branch_labels = None
depends_on = None


INDEXES = {
    "ix_songs_artist": ["artist"],
    "ix_songs_album": ["album"],
    "ix_songs_title": ["title"],
    "ix_songs_genre": ["genre"],
    "ix_songs_codec": ["codec"],
    "ix_songs_bitrate": ["bitrate"],
    "ix_songs_year": ["year"],
    "ix_songs_created_at": ["created_at"],
    "ix_songs_last_modified": ["last_modified"],
    "ix_songs_available_artist_album": ["availability_status", "artist", "album"],
    "ix_songs_available_created": ["availability_status", "created_at"],
}


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("songs")}
    existing = {index["name"] for index in inspector.get_indexes("songs")}
    for name, index_columns in INDEXES.items():
        if name not in existing and set(index_columns) <= columns:
            op.create_index(name, "songs", index_columns)


def downgrade() -> None:
    pass
