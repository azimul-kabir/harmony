from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.database.base import Base
from app.database.database import engine

# Import models so SQLAlchemy knows about them.
from app.database import models  # noqa: F401


_METADATA_APPLICATION_SONG_COLUMNS = (
    # ``cover_url`` predates the Alembic chain and can be absent from an
    # upgraded legacy database even though current ORM queries select it.
    ("cover_url", "VARCHAR"),
    ("musicbrainz_release_group_id", "VARCHAR"),
    ("musicbrainz_release_artist_id", "VARCHAR"),
    ("release_date", "VARCHAR(10)"),
    ("original_release_date", "VARCHAR(10)"),
)

_DOWNLOAD_JOB_COMPAT_COLUMNS = (
    ("cover_url", "VARCHAR"),
    ("error_message", "VARCHAR"),
    ("source_url", "VARCHAR"),
    ("updated_at", "DATETIME"),
    ("pipeline_stage", "VARCHAR(40)"),
    ("progress_percent", "INTEGER"),
    ("heartbeat_at", "DATETIME"),
    ("worker_name", "VARCHAR(80)"),
    ("bytes_downloaded", "INTEGER"),
    ("bytes_total", "INTEGER"),
    ("transfer_rate_bps", "INTEGER"),
    ("eta_seconds", "INTEGER"),
)


def _repair_stamped_metadata_application_schema(connection) -> None:
    """Repair a partially deployed 0014 schema that was incorrectly stamped.

    A released container can have Alembic recorded at ``head`` while one or
    more 0014 Song columns are absent (for example after an interrupted or
    older deployment). Alembic correctly treats that database as current, but
    SQLAlchemy then selects a column SQLite does not have. Keep this repair
    deliberately narrow and idempotent so startup restores the schema rather
    than making every library query fail.
    """
    columns = {column["name"] for column in inspect(connection).get_columns("songs")}
    for name, column_type in _METADATA_APPLICATION_SONG_COLUMNS:
        if name not in columns:
            connection.execute(text(f"ALTER TABLE songs ADD COLUMN {name} {column_type}"))

    indexes = {index["name"] for index in inspect(connection).get_indexes("songs")}
    for name, column in (
        ("ix_songs_musicbrainz_release_group_id", "musicbrainz_release_group_id"),
        ("ix_songs_musicbrainz_release_artist_id", "musicbrainz_release_artist_id"),
    ):
        if name not in indexes:
            connection.execute(text(f"CREATE INDEX {name} ON songs ({column})"))


def _repair_stamped_download_schema(connection) -> None:
    """Reconcile additive DownloadJob fields missing from legacy databases."""
    inspector = inspect(connection)
    if "download_jobs" not in inspector.get_table_names():
        return
    columns = {
        column["name"] for column in inspector.get_columns("download_jobs")
    }
    for name, column_type in _DOWNLOAD_JOB_COMPAT_COLUMNS:
        if name not in columns:
            connection.execute(
                text(f"ALTER TABLE download_jobs ADD COLUMN {name} {column_type}")
            )
    connection.execute(
        text(
            "UPDATE download_jobs SET updated_at = "
            "COALESCE(updated_at, completed_at, started_at, created_at) "
            "WHERE updated_at IS NULL"
        )
    )
    indexes = {
        index["name"] for index in inspect(connection).get_indexes("download_jobs")
    }
    if "ix_download_jobs_heartbeat_at" not in indexes:
        connection.execute(
            text(
                "CREATE INDEX ix_download_jobs_heartbeat_at "
                "ON download_jobs (heartbeat_at)"
            )
        )


def init_db() -> None:
    # A brand-new installation is bootstrapped from the current ORM schema and
    # stamped at head.  The migration chain deliberately starts from Harmony's
    # pre-existing ``songs`` table, so running it against an empty database is
    # neither necessary nor valid.  Existing databases retain the additive
    # upgrade path below.
    is_fresh = "songs" not in inspect(engine).get_table_names()
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))

    with engine.begin() as connection:
        config.attributes["connection"] = connection
        if is_fresh:
            # The historical migration chain begins with Harmony's original
            # schema, so a truly new database is created from the current ORM
            # metadata and stamped rather than replaying legacy migrations.
            Base.metadata.create_all(bind=connection)
            command.stamp(config, "head")
        else:
            # Do not call create_all before upgrading an existing database.
            # It would create tables from a later ORM schema (for example,
            # metadata_suggestions) before Alembic reaches the revision that
            # owns them, causing the upgrade to fail with "table already
            # exists" and the container to restart continuously.
            command.upgrade(config, "head")

        # Older v1.6 deployments could be stamped at head despite an
        # incomplete 0014 migration. Alembic cannot replay a revision already
        # recorded as applied, so reconcile the known additive Song fields.
        _repair_stamped_metadata_application_schema(connection)
        _repair_stamped_download_schema(connection)
