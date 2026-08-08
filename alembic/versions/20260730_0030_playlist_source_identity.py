"""Add provider-neutral identities to playlist sync sources.

Legacy spotify_id/spotify_url columns remain populated as compatibility mirrors;
provider, external_id and source_url are the authoritative source identity.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260730_0030"
down_revision = "20260729_0029"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = inspect(bind).get_table_names()
    if "sync_sources" in tables:
        columns = {c["name"] for c in inspect(bind).get_columns("sync_sources")}
        with op.batch_alter_table("sync_sources") as batch:
            if "provider" not in columns:
                batch.add_column(sa.Column("provider", sa.String(32), nullable=False, server_default="spotify"))
            if "external_id" not in columns:
                batch.add_column(sa.Column("external_id", sa.String(), nullable=True))
            if "source_url" not in columns:
                batch.add_column(sa.Column("source_url", sa.String(), nullable=True))
        op.execute("UPDATE sync_sources SET provider='spotify' WHERE provider IS NULL OR provider='' ")
        op.execute("UPDATE sync_sources SET external_id=spotify_id WHERE external_id IS NULL")
        op.execute("UPDATE sync_sources SET source_url=spotify_url WHERE source_url IS NULL")
        inspector = inspect(bind)
        uniques = inspector.get_unique_constraints("sync_sources")
        unique_columns = {tuple(item.get("column_names") or ()) for item in uniques}
        indexes = {item["name"] for item in inspector.get_indexes("sync_sources")}
        naming = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
        with op.batch_alter_table("sync_sources", naming_convention=naming) as batch:
            for unique in uniques:
                if unique.get("column_names") == ["spotify_id"]:
                    batch.drop_constraint(unique.get("name") or "uq_sync_sources_spotify_id", type_="unique")
            if ("provider", "external_id") not in unique_columns:
                batch.create_unique_constraint("uq_sync_source_provider_external_id", ["provider", "external_id"])
            if "ix_sync_sources_provider" not in indexes:
                batch.create_index("ix_sync_sources_provider", ["provider"])
            if "ix_sync_sources_external_id" not in indexes:
                batch.create_index("ix_sync_sources_external_id", ["external_id"])
            # The default is needed only while old rows are being upgraded.
            # New writes must always choose their provider explicitly (the ORM
            # retains a Python default for legacy call sites).
            batch.alter_column("provider", server_default=None)

    if "playlists" in tables:
        columns = {c["name"] for c in inspect(bind).get_columns("playlists")}
        with op.batch_alter_table("playlists") as batch:
            if "source_provider" not in columns:
                batch.add_column(sa.Column("source_provider", sa.String(32), nullable=True))
            if "source_external_id" not in columns:
                batch.add_column(sa.Column("source_external_id", sa.String(), nullable=True))
            if "source_url" not in columns:
                batch.add_column(sa.Column("source_url", sa.String(), nullable=True))
        op.execute("UPDATE playlists SET source_provider='spotify', source_external_id=spotify_id WHERE playlist_kind='source' AND spotify_id IS NOT NULL AND source_external_id IS NULL")
        inspector = inspect(bind)
        playlist_uniques = {
            tuple(item.get("column_names") or ())
            for item in inspector.get_unique_constraints("playlists")
        }
        playlist_indexes = {item["name"] for item in inspector.get_indexes("playlists")}
        with op.batch_alter_table("playlists") as batch:
            if ("source_provider", "source_external_id") not in playlist_uniques:
                batch.create_unique_constraint("uq_playlist_source_identity", ["source_provider", "source_external_id"])
            if "ix_playlists_source_provider" not in playlist_indexes:
                batch.create_index("ix_playlists_source_provider", ["source_provider"])
            if "ix_playlists_source_external_id" not in playlist_indexes:
                batch.create_index("ix_playlists_source_external_id", ["source_external_id"])


def downgrade():
    bind = op.get_bind()
    tables = inspect(bind).get_table_names()
    if "sync_sources" in tables:
        youtube_count = bind.execute(
            sa.text("SELECT COUNT(*) FROM sync_sources WHERE provider <> 'spotify'")
        ).scalar_one()
        if youtube_count:
            raise RuntimeError(
                "Cannot downgrade playlist source identity while non-Spotify sources exist. "
                "Delete those sources first or keep revision 20260730_0030."
            )
    with op.batch_alter_table("playlists") as batch:
        batch.drop_constraint("uq_playlist_source_identity", type_="unique")
        batch.drop_index("ix_playlists_source_external_id")
        batch.drop_index("ix_playlists_source_provider")
        batch.drop_column("source_url")
        batch.drop_column("source_external_id")
        batch.drop_column("source_provider")
    with op.batch_alter_table("sync_sources") as batch:
        batch.drop_constraint("uq_sync_source_provider_external_id", type_="unique")
        batch.drop_index("ix_sync_sources_external_id")
        batch.drop_index("ix_sync_sources_provider")
        batch.drop_column("source_url")
        batch.drop_column("external_id")
        batch.drop_column("provider")
        batch.create_unique_constraint("uq_sync_sources_spotify_id", ["spotify_id"])
