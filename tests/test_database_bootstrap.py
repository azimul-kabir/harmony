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
    assert revision == "20260722_0015"

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
    assert revision == "20260722_0015"


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
    assert revision == "20260722_0015"
