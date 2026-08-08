"""Map multiple provider identities to one library song.

Revision ID: 20260727_0027
Revises: 20260725_0026
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260727_0027"
down_revision = "20260725_0026"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "songs" not in inspector.get_table_names():
        return
    if "song_source_identities" not in inspector.get_table_names():
        op.create_table(
            "song_source_identities",
            sa.Column("provider", sa.String(80), nullable=False),
            sa.Column("item_id", sa.String(255), nullable=False),
            sa.Column(
                "song_id",
                sa.Integer(),
                sa.ForeignKey("songs.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("provider", "item_id"),
        )
        op.create_index(
            "ix_song_source_identities_song_id",
            "song_source_identities",
            ["song_id"],
        )
    if "spotify_track_id" in {
        column["name"] for column in inspect(bind).get_columns("songs")
    }:
        op.execute(
            "INSERT OR IGNORE INTO song_source_identities "
            "(provider, item_id, song_id, created_at) "
            "SELECT 'spotify', spotify_track_id, id, CURRENT_TIMESTAMP "
            "FROM songs WHERE spotify_track_id IS NOT NULL"
        )


def downgrade():
    if "song_source_identities" in inspect(op.get_bind()).get_table_names():
        op.drop_table("song_source_identities")
