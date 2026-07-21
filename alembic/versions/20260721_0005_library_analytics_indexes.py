"""Add indexes for Library album analytics."""

from alembic import op
import sqlalchemy as sa

revision = "20260721_0005"
down_revision = "20260721_0004"
branch_labels = None
depends_on = None


INDEXES = {
    "ix_songs_album_artist": ["album_artist"],
    "ix_songs_available_album_artist": [
        "availability_status",
        "album",
        "album_artist",
    ],
    "ix_songs_available_year_album": ["availability_status", "year", "album"],
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
