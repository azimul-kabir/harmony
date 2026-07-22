from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.database.base import Base
from app.database.database import engine

# Import models so SQLAlchemy knows about them.
from app.database import models  # noqa: F401


_METADATA_APPLICATION_SONG_COLUMNS = (
    ("musicbrainz_release_group_id", "VARCHAR"),
    ("musicbrainz_release_artist_id", "VARCHAR"),
    ("release_date", "VARCHAR(10)"),
    ("original_release_date", "VARCHAR(10)"),
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
