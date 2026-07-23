"""add Spotify genre download and provenance fields

Revision ID: 20260722_0016
Revises: 20260722_0015
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260722_0016"
down_revision = "20260722_0015"
branch_labels = None
depends_on = None

def upgrade():
    inspector = inspect(op.get_bind())
    if "genre_provenance" not in {column["name"] for column in inspector.get_columns("songs")}:
        op.add_column("songs", sa.Column("genre_provenance", sa.Text(), nullable=True))
    # Some pre-v1.6 library-only installations legitimately have no historical
    # download queue table.  Preserve their forward upgrade path.
    if "download_jobs" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("download_jobs")}
    for name, column in (
        ("genre", sa.Column("genre", sa.String(), nullable=True)),
        ("spotify_artist_ids", sa.Column("spotify_artist_ids", sa.Text(), nullable=True)),
        ("genre_provenance", sa.Column("genre_provenance", sa.Text(), nullable=True)),
    ):
        if name not in columns:
            op.add_column("download_jobs", column)

def downgrade():
    op.drop_column("download_jobs", "genre_provenance")
    op.drop_column("download_jobs", "spotify_artist_ids")
    op.drop_column("download_jobs", "genre")
    op.drop_column("songs", "genre_provenance")
