"""Fresh-install contract: bootstrap current schema, then stamp Alembic head."""

from sqlalchemy import create_engine, inspect, text
from alembic import command
from alembic.config import Config
from pathlib import Path

from app.database import init_db as database_init


def test_fresh_install_bootstraps_and_stamps_head(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    monkeypatch.setattr(database_init, "engine", engine)

    database_init.init_db()

    tables = set(inspect(engine).get_table_names())
    revision = (
        engine.connect()
        .execute(text("SELECT version_num FROM alembic_version"))
        .scalar_one()
    )
    assert {
        "songs",
        "metadata_application_batches",
        "metadata_application_locks",
    } <= tables
    assert revision == "20260723_0018"

    # A second bootstrap detects the existing database and is an Alembic no-op.
    database_init.init_db()
    assert (
        engine.connect()
        .execute(text("SELECT version_num FROM alembic_version"))
        .scalar_one()
        == revision
    )


def test_existing_database_upgrades_without_precreating_future_tables(
    tmp_path, monkeypatch
):
    """Existing v1.5 databases must let Alembic create v1.6 tables itself."""
    engine = create_engine(f"sqlite:///{tmp_path / 'existing.db'}")
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))

    with engine.begin() as connection:
        # The migration chain starts from Harmony's pre-existing songs table.
        connection.exec_driver_sql(
            "CREATE TABLE songs ("
            "id INTEGER PRIMARY KEY, "
            "path VARCHAR NOT NULL UNIQUE, "
            "filename VARCHAR NOT NULL, "
            "modified_time INTEGER, "
            "created_at DATETIME"
            ")"
        )
        config.attributes["connection"] = connection
        command.upgrade(config, "20260721_0008")

    monkeypatch.setattr(database_init, "engine", engine)
    database_init.init_db()

    tables = set(inspect(engine).get_table_names())
    revision = (
        engine.connect()
        .execute(text("SELECT version_num FROM alembic_version"))
        .scalar_one()
    )
    assert {"metadata_suggestions", "metadata_application_locks"} <= tables
    assert revision == "20260723_0018"


def test_existing_database_retries_interrupted_metadata_migration(
    tmp_path, monkeypatch
):
    """A restart after SQLite DDL must finish the unrecorded revision."""
    engine = create_engine(f"sqlite:///{tmp_path / 'interrupted.db'}")
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE songs ("
            "id INTEGER PRIMARY KEY, path VARCHAR NOT NULL UNIQUE, "
            "filename VARCHAR NOT NULL, modified_time INTEGER, created_at DATETIME)"
        )
        config.attributes["connection"] = connection
        command.upgrade(config, "20260721_0009")
        # Reproduce an interrupted run: DDL persisted, but the revision did not.
        connection.execute(
            text("UPDATE alembic_version SET version_num = '20260721_0008'")
        )

    monkeypatch.setattr(database_init, "engine", engine)
    database_init.init_db()

    revision = (
        engine.connect()
        .execute(text("SELECT version_num FROM alembic_version"))
        .scalar_one()
    )
    assert revision == "20260723_0018"


def test_existing_database_retries_interrupted_metadata_health_migration(
    tmp_path, monkeypatch
):
    """An unrecorded metadata_issues table must not cause a restart loop."""
    engine = create_engine(f"sqlite:///{tmp_path / 'interrupted-health.db'}")
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE songs ("
            "id INTEGER PRIMARY KEY, path VARCHAR NOT NULL UNIQUE, "
            "filename VARCHAR NOT NULL, modified_time INTEGER, created_at DATETIME)"
        )
        config.attributes["connection"] = connection
        command.upgrade(config, "20260721_0010")
        # Reproduce a restart after SQLite committed the DDL but before
        # Alembic advanced its version marker.
        connection.execute(
            text("UPDATE alembic_version SET version_num = '20260721_0009'")
        )

    monkeypatch.setattr(database_init, "engine", engine)
    database_init.init_db()

    assert (
        engine.connect()
        .execute(text("SELECT version_num FROM alembic_version"))
        .scalar_one()
        == "20260723_0018"
    )


def test_existing_database_retries_interrupted_metadata_health_indexes_migration(
    tmp_path, monkeypatch
):
    """A restart after the 0011 SQLite DDL must complete the upgrade."""
    engine = create_engine(f"sqlite:///{tmp_path / 'interrupted-health-indexes.db'}")
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE songs ("
            "id INTEGER PRIMARY KEY, path VARCHAR NOT NULL UNIQUE, "
            "filename VARCHAR NOT NULL, modified_time INTEGER, created_at DATETIME)"
        )
        config.attributes["connection"] = connection
        command.upgrade(config, "20260722_0011")
        # Reproduce a container exit after the DDL completed but before
        # Alembic persisted the migration revision.
        connection.execute(
            text("UPDATE alembic_version SET version_num = '20260721_0010'")
        )

    monkeypatch.setattr(database_init, "engine", engine)
    database_init.init_db()

    assert (
        engine.connect()
        .execute(text("SELECT version_num FROM alembic_version"))
        .scalar_one()
        == "20260723_0018"
    )


def test_existing_database_repairs_missing_song_columns_when_batch_table_exists(
    tmp_path, monkeypatch
):
    """A pre-created application table must not skip the rest of revision 0014."""
    engine = create_engine(f"sqlite:///{tmp_path / 'partial-application.db'}")
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE songs ("
            "id INTEGER PRIMARY KEY, path VARCHAR NOT NULL UNIQUE, "
            "filename VARCHAR NOT NULL, modified_time INTEGER, created_at DATETIME)"
        )
        config.attributes["connection"] = connection
        command.upgrade(config, "20260722_0013")
        database_init.Base.metadata.tables["metadata_application_batches"].create(
            bind=connection
        )

    monkeypatch.setattr(database_init, "engine", engine)
    database_init.init_db()

    song_columns = {column["name"] for column in inspect(engine).get_columns("songs")}
    assert {
        "musicbrainz_release_group_id",
        "musicbrainz_release_artist_id",
        "release_date",
        "original_release_date",
    } <= song_columns
    assert (
        engine.connect()
        .execute(text("SELECT version_num FROM alembic_version"))
        .scalar_one()
        == "20260723_0018"
    )


def test_existing_database_repairs_missing_song_columns_when_incorrectly_at_head(
    tmp_path, monkeypatch
):
    """A mistakenly stamped v1.6 database must not remain permanently broken."""
    engine = create_engine(f"sqlite:///{tmp_path / 'stamped-incomplete.db'}")
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE songs ("
            "id INTEGER PRIMARY KEY, path VARCHAR NOT NULL UNIQUE, "
            "filename VARCHAR NOT NULL, modified_time INTEGER, created_at DATETIME)"
        )
        config.attributes["connection"] = connection
        command.upgrade(config, "20260722_0013")
        connection.execute(
            text("UPDATE alembic_version SET version_num = '20260722_0015'")
        )

    monkeypatch.setattr(database_init, "engine", engine)
    database_init.init_db()

    song_columns = {column["name"] for column in inspect(engine).get_columns("songs")}
    assert {
        "musicbrainz_release_group_id",
        "musicbrainz_release_artist_id",
        "release_date",
        "original_release_date",
    } <= song_columns


def test_existing_database_recovers_from_legacy_precreated_metadata_schema(
    tmp_path, monkeypatch
):
    """A database pre-created by the old bootstrap must still reach head."""
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-precreated.db'}")
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))

    with engine.begin() as connection:
        # This is the state produced when the former bootstrap called
        # create_all() before upgrading a database recorded at 0008.
        database_init.Base.metadata.create_all(bind=connection)
        connection.exec_driver_sql(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
        )
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES ('20260721_0008')")
        )

    monkeypatch.setattr(database_init, "engine", engine)
    database_init.init_db()

    assert (
        engine.connect()
        .execute(text("SELECT version_num FROM alembic_version"))
        .scalar_one()
        == "20260723_0018"
    )
