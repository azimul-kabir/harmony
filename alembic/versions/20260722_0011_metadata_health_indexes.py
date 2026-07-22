"""Add metadata issue entity and first-detection indexes.

Revision ID: 20260722_0011
Revises: 20260721_0010
"""
from alembic import op
import sqlalchemy as sa

revision = "20260722_0011"
down_revision = "20260721_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite DDL can persist when a container is stopped before Alembic writes
    # the revision marker.  Check each additive change so the next startup can
    # resume that interrupted migration rather than crash on a duplicate
    # column or index and enter Docker's restart loop.
    bind = op.get_bind()
    song_columns = {column["name"] for column in sa.inspect(bind).get_columns("songs")}
    for column in (
        sa.Column("track_total", sa.Integer(), nullable=True),
        sa.Column("disc_total", sa.Integer(), nullable=True),
        sa.Column("musicbrainz_release_id", sa.String(), nullable=True),
        sa.Column("musicbrainz_artist_id", sa.String(), nullable=True),
        sa.Column("compilation", sa.Boolean(), nullable=True),
    ):
        if column.name not in song_columns:
            op.add_column("songs", column)

    song_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("songs")}
    issue_indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("metadata_issues")
    }
    for name, table, columns, existing_indexes in (
        ("ix_songs_musicbrainz_release_id", "songs", ["musicbrainz_release_id"], song_indexes),
        ("ix_songs_musicbrainz_artist_id", "songs", ["musicbrainz_artist_id"], song_indexes),
        ("ix_metadata_issues_entity", "metadata_issues", ["entity_type", "entity_id", "status"], issue_indexes),
        ("ix_metadata_issues_first_detected", "metadata_issues", ["first_detected_at"], issue_indexes),
    ):
        if name not in existing_indexes:
            op.create_index(name, table, columns)


def downgrade() -> None:
    op.drop_index("ix_metadata_issues_first_detected", table_name="metadata_issues")
    op.drop_index("ix_metadata_issues_entity", table_name="metadata_issues")
    op.drop_index("ix_songs_musicbrainz_artist_id", table_name="songs")
    op.drop_index("ix_songs_musicbrainz_release_id", table_name="songs")
    op.drop_column("songs", "compilation")
    op.drop_column("songs", "musicbrainz_artist_id")
    op.drop_column("songs", "musicbrainz_release_id")
    op.drop_column("songs", "disc_total")
    op.drop_column("songs", "track_total")
