from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_library_foundation_migrates_existing_songs_table(tmp_path):
    database = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{database}")

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE songs ("
            "id INTEGER PRIMARY KEY, "
            "path VARCHAR NOT NULL UNIQUE, "
            "filename VARCHAR NOT NULL"
            ")"
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
