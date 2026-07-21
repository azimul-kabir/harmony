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
    op.add_column("songs", sa.Column("track_total", sa.Integer(), nullable=True))
    op.add_column("songs", sa.Column("disc_total", sa.Integer(), nullable=True))
    op.add_column("songs", sa.Column("musicbrainz_release_id", sa.String(), nullable=True))
    op.add_column("songs", sa.Column("musicbrainz_artist_id", sa.String(), nullable=True))
    op.add_column("songs", sa.Column("compilation", sa.Boolean(), nullable=True))
    op.create_index("ix_songs_musicbrainz_release_id", "songs", ["musicbrainz_release_id"])
    op.create_index("ix_songs_musicbrainz_artist_id", "songs", ["musicbrainz_artist_id"])
    op.create_index("ix_metadata_issues_entity", "metadata_issues", ["entity_type", "entity_id", "status"])
    op.create_index("ix_metadata_issues_first_detected", "metadata_issues", ["first_detected_at"])


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
