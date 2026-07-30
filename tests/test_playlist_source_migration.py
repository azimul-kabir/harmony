from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect


PREVIOUS_REVISION = "20260729_0029"


def _config(connection):
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.attributes["connection"] = connection
    return config


def _legacy_schema(connection):
    connection.exec_driver_sql(
        "CREATE TABLE sync_sources (id INTEGER PRIMARY KEY, type VARCHAR NOT NULL, "
        "spotify_id VARCHAR NOT NULL UNIQUE, spotify_url VARCHAR NOT NULL, "
        "name VARCHAR NOT NULL, enabled BOOLEAN NOT NULL)"
    )
    connection.exec_driver_sql(
        "CREATE TABLE playlists (id INTEGER PRIMARY KEY, spotify_id VARCHAR UNIQUE, "
        "name VARCHAR NOT NULL, playlist_kind VARCHAR NOT NULL DEFAULT 'source')"
    )
    connection.exec_driver_sql(
        "INSERT INTO sync_sources VALUES (1, 'playlist', 'spotify-one', "
        "'https://open.spotify.com/playlist/spotify-one', 'One', 1)"
    )
    connection.exec_driver_sql(
        "INSERT INTO playlists VALUES (1, NULL, 'Local', 'local')"
    )


def test_source_identity_upgrade_backfills_without_permanent_default(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'source-upgrade.db'}")
    with engine.begin() as connection:
        _legacy_schema(connection)
        config = _config(connection)
        command.stamp(config, PREVIOUS_REVISION)
        command.upgrade(config, "head")

        assert connection.exec_driver_sql(
            "SELECT provider, external_id, source_url FROM sync_sources"
        ).one() == (
            "spotify",
            "spotify-one",
            "https://open.spotify.com/playlist/spotify-one",
        )
        provider = next(
            column for column in inspect(connection).get_columns("sync_sources")
            if column["name"] == "provider"
        )
        assert provider["default"] is None
        assert connection.exec_driver_sql(
            "SELECT source_provider, source_external_id FROM playlists"
        ).one() == (None, None)


def test_source_identity_downgrade_restores_spotify_uniqueness(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'source-downgrade.db'}")
    with engine.begin() as connection:
        _legacy_schema(connection)
        config = _config(connection)
        command.stamp(config, PREVIOUS_REVISION)
        command.upgrade(config, "head")
        command.downgrade(config, PREVIOUS_REVISION)

        uniques = inspect(connection).get_unique_constraints("sync_sources")
        assert any(item["column_names"] == ["spotify_id"] for item in uniques)


def test_source_identity_downgrade_rejects_youtube_music_data(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'source-reject.db'}")
    with engine.begin() as connection:
        _legacy_schema(connection)
        config = _config(connection)
        command.stamp(config, PREVIOUS_REVISION)
        command.upgrade(config, "head")
        connection.exec_driver_sql(
            "UPDATE sync_sources SET provider='youtube_music', external_id='PL123456' WHERE id=1"
        )

        with pytest.raises(RuntimeError, match="non-Spotify sources exist"):
            command.downgrade(config, PREVIOUS_REVISION)
