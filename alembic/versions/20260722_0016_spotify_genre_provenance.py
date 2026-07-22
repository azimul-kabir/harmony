"""add Spotify genre download and provenance fields

Revision ID: 20260722_0016
Revises: 20260722_0015
"""
from alembic import op
import sqlalchemy as sa

revision = "20260722_0016"
down_revision = "20260722_0015"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("songs", sa.Column("genre_provenance", sa.Text(), nullable=True))
    op.add_column("download_jobs", sa.Column("genre", sa.String(), nullable=True))
    op.add_column("download_jobs", sa.Column("spotify_artist_ids", sa.Text(), nullable=True))
    op.add_column("download_jobs", sa.Column("genre_provenance", sa.Text(), nullable=True))

def downgrade():
    op.drop_column("download_jobs", "genre_provenance")
    op.drop_column("download_jobs", "spotify_artist_ids")
    op.drop_column("download_jobs", "genre")
    op.drop_column("songs", "genre_provenance")
