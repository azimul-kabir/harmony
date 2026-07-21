"""Add reusable, content-addressed artwork storage."""

from alembic import op
import sqlalchemy as sa

revision = "20260721_0002"
down_revision = "20260721_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())

    if "artwork" not in tables:
        op.create_table(
            "artwork",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("checksum", sa.String(64), nullable=False, unique=True),
            sa.Column("cache_path", sa.String(), nullable=False, unique=True),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("mime_type", sa.String(), nullable=False),
            sa.Column("width", sa.Integer(), nullable=True),
            sa.Column("height", sa.Integer(), nullable=True),
            sa.Column("file_size", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(), nullable=True),
            sa.Column("provider_id", sa.String(), nullable=True),
            sa.Column("original_url", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_artwork_checksum", "artwork", ["checksum"], unique=True)
        op.create_index("ix_artwork_provider_id", "artwork", ["provider_id"])

    song_columns = {column["name"] for column in sa.inspect(connection).get_columns("songs")}
    if "artwork_id" not in song_columns:
        op.add_column("songs", sa.Column("artwork_id", sa.Integer(), nullable=True))
        op.create_index("ix_songs_artwork_id", "songs", ["artwork_id"])


def downgrade() -> None:
    # Additive migration: cached resources and song associations are preserved.
    pass
