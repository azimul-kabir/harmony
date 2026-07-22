"""Fresh-install contract: bootstrap current schema, then stamp Alembic head."""

from sqlalchemy import create_engine, inspect, text

from app.database import init_db as database_init


def test_fresh_install_bootstraps_and_stamps_head(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    monkeypatch.setattr(database_init, "engine", engine)

    database_init.init_db()

    tables = set(inspect(engine).get_table_names())
    revision = engine.connect().execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert {"songs", "metadata_application_batches", "metadata_application_locks"} <= tables
    assert revision == "20260722_0015"

    # A second bootstrap detects the existing database and is an Alembic no-op.
    database_init.init_db()
    assert engine.connect().execute(text("SELECT version_num FROM alembic_version")).scalar_one() == revision
