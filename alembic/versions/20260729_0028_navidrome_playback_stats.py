"""Cache Navidrome song playback metadata for auto-playlists.

Revision ID: 20260729_0028
Revises: 20260727_0027
"""

from alembic import op
import sqlalchemy as sa

revision = "20260729_0028"
down_revision = "20260727_0027"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "songs",
        sa.Column(
            "navidrome_play_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "songs", sa.Column("navidrome_last_played_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "songs", sa.Column("navidrome_starred_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "songs", sa.Column("navidrome_stats_synced_at", sa.DateTime(), nullable=True)
    )
    op.create_index(
        "ix_songs_navidrome_last_played_at", "songs", ["navidrome_last_played_at"]
    )
    op.create_index("ix_songs_navidrome_starred_at", "songs", ["navidrome_starred_at"])


def downgrade():
    op.drop_index("ix_songs_navidrome_starred_at", table_name="songs")
    op.drop_index("ix_songs_navidrome_last_played_at", table_name="songs")
    op.drop_column("songs", "navidrome_stats_synced_at")
    op.drop_column("songs", "navidrome_starred_at")
    op.drop_column("songs", "navidrome_last_played_at")
    op.drop_column("songs", "navidrome_play_count")
