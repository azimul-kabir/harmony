from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_library_foundation_migrates_existing_songs_table(tmp_path):
    database = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{database}")

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE songs ("
            "id INTEGER PRIMARY KEY, "
            "path VARCHAR NOT NULL UNIQUE, "
            "filename VARCHAR NOT NULL, "
            "modified_time INTEGER, "
            "created_at DATETIME"
            ")"
        )
        connection.execute(
            text(
                "INSERT INTO songs (id, path, filename, modified_time, created_at) "
                "VALUES (1, '/music/legacy.mp3', 'legacy.mp3', 1720000000, NULL)"
            )
        )

    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))

    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    columns = {column["name"] for column in inspect(engine).get_columns("songs")}
    assert {
        "bitrate",
        "codec",
        "sample_rate",
        "artwork_status",
        "availability_status",
        "download_source",
        "musicbrainz_recording_id",
        "artwork_id",
    } <= columns
    assert "artwork" in inspect(engine).get_table_names()
    artwork_columns = {
        column["name"] for column in inspect(engine).get_columns("artwork")
    }
    assert {
        "checksum",
        "cache_path",
        "source",
        "mime_type",
        "provider",
        "provider_id",
        "original_url",
    } <= artwork_columns
    assert "library_search" in inspect(engine).get_table_names()
    search_columns = {
        column["name"] for column in inspect(engine).get_columns("library_search")
    }
    assert {
        "song_id",
        "title",
        "artist",
        "album",
        "genre",
        "playlist",
        "filename",
        "spotify_id",
        "musicbrainz_id",
        "isrc",
    } <= search_columns
    song_indexes = {index["name"] for index in inspect(engine).get_indexes("songs")}
    assert {
        "ix_songs_codec",
        "ix_songs_bitrate",
    } <= song_indexes
    assert "bulk_operation_items" in inspect(engine).get_table_names()
    with engine.connect() as connection:
        created_at = connection.execute(
            text("SELECT created_at FROM songs WHERE id = 1")
        ).scalar_one()
    assert created_at is not None
    task_columns = {
        column["name"] for column in inspect(engine).get_columns("tasks")
    }
    assert {"operation_payload", "output_path"} <= task_columns
    tables = set(inspect(engine).get_table_names())
    assert {"metadata_suggestions", "metadata_history"} <= tables
    suggestion_columns = {column["name"] for column in inspect(engine).get_columns("metadata_suggestions")}
    assert {"entity_type", "field_name", "suggested_value", "confidence_level", "positive_evidence", "status"} <= suggestion_columns
    with engine.connect() as connection:
        assert connection.execute(text("SELECT filename FROM songs WHERE id = 1")).scalar_one() == "legacy.mp3"
