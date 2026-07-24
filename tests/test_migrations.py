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
        "track_total",
        "disc_total",
        "musicbrainz_release_id",
        "musicbrainz_artist_id",
        "compilation",
        "lyrics",
        "lyrics_source",
        "lyrics_synced",
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
    assert {"metadata_suggestions", "metadata_history", "metadata_issues"} <= tables
    suggestion_columns = {column["name"] for column in inspect(engine).get_columns("metadata_suggestions")}
    assert {"entity_type", "field_name", "suggested_value", "confidence_level", "positive_evidence", "status"} <= suggestion_columns
    with engine.connect() as connection:
        assert connection.execute(text("SELECT filename FROM songs WHERE id = 1")).scalar_one() == "legacy.mp3"


def test_discovery_migration_preserves_populated_metadata_and_jobs(tmp_path):
    database=tmp_path/"pre-discovery.db";engine=create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE songs (id INTEGER PRIMARY KEY,path VARCHAR NOT NULL UNIQUE,filename VARCHAR NOT NULL,modified_time INTEGER,created_at DATETIME)")
        connection.exec_driver_sql("INSERT INTO songs VALUES (1,'/music/kept.mp3','kept.mp3',1720000000,'2026-01-01')")
    root=Path(__file__).resolve().parents[1];config=Config(str(root/"alembic.ini"));config.set_main_option("script_location",str(root/"alembic"))
    with engine.begin() as connection:
        config.attributes["connection"]=connection;command.upgrade(config,"20260722_0012")
        connection.execute(text("INSERT INTO tasks (id,name,spotify_url,task_type,status,total_items,completed_items,skipped_items,failed_items,created_at,resumable) VALUES (1,'Kept','library://kept','library_maintenance','completed',1,1,0,0,'2026-01-01',0)"))
        connection.execute(text("INSERT INTO metadata_suggestions (id,entity_type,entity_id,field_name,suggested_value,provider,confidence_level,status,created_at) VALUES (1,'song',1,'title','\"Proposed\"','test','high','pending','2026-01-01')"))
        connection.execute(text("INSERT INTO metadata_history (id,entity_type,entity_id,field_name,new_value,changed_at,change_source,audio_file_modified,reversible) VALUES (1,'song',1,'title','\"Kept\"','2026-01-01','manual',0,1)"))
        connection.execute(text("INSERT INTO metadata_issues (id,identity_key,rule_id,rule_version,entity_type,entity_id,song_id,severity,status,title,explanation,automatically_repairable,first_detected_at,last_detected_at) VALUES (1,'identity','missing_title','1','song','1',1,'warning','open','Missing','Missing title',0,'2026-01-01','2026-01-01')"))
        command.upgrade(config,"head")
    tables=set(inspect(engine).get_table_names())
    assert {"metadata_discoveries","metadata_match_results","metadata_discovery_locks"}<=tables
    with engine.connect() as connection:
        assert connection.execute(text("SELECT filename FROM songs WHERE id=1")).scalar_one()=="kept.mp3"
        assert connection.execute(text("SELECT name FROM tasks WHERE id=1")).scalar_one()=="Kept"
        assert connection.execute(text("SELECT provider FROM metadata_suggestions WHERE id=1")).scalar_one()=="test"
        assert connection.execute(text("SELECT change_source FROM metadata_history WHERE id=1")).scalar_one()=="manual"
        assert connection.execute(text("SELECT rule_id FROM metadata_issues WHERE id=1")).scalar_one()=="missing_title"
    discovery_indexes={x["name"] for x in inspect(engine).get_indexes("metadata_discoveries")}
    result_indexes={x["name"] for x in inspect(engine).get_indexes("metadata_match_results")}
    assert {"ix_metadata_discoveries_entity","ix_metadata_discoveries_filter","ix_metadata_discoveries_job"}<=discovery_indexes
    assert {"ix_metadata_match_results_ranking","ix_metadata_match_results_confidence","uq_metadata_match_result_provider"}<=result_indexes


def test_download_telemetry_migrates_existing_download_jobs(tmp_path):
    database = tmp_path / "pre-telemetry.db"
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE download_jobs ("
            "id INTEGER PRIMARY KEY, status VARCHAR NOT NULL, "
            "title VARCHAR NOT NULL, artist VARCHAR NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO download_jobs VALUES (1, 'running', 'Kept', 'Artist')"
        )
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.stamp(config, "20260723_0018")
        command.upgrade(config, "head")
    download_columns = {
        column["name"] for column in inspect(engine).get_columns("download_jobs")
    }
    assert {
        "pipeline_stage",
        "progress_percent",
        "heartbeat_at",
        "worker_name",
        "bytes_downloaded",
        "bytes_total",
        "transfer_rate_bps",
        "eta_seconds",
        "queue_position",
    } <= download_columns
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT title FROM download_jobs WHERE id=1")
        ).scalar_one() == "Kept"


def test_playlist_metadata_migrates_existing_playlist_tracks(tmp_path):
    database = tmp_path / "pre-playlist-metadata.db"
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE playlist_tracks ("
            "playlist_id INTEGER NOT NULL, "
            "spotify_track_id VARCHAR NOT NULL, "
            "position INTEGER NOT NULL, "
            "added_at DATETIME, "
            "PRIMARY KEY (playlist_id, spotify_track_id))"
        )
        connection.exec_driver_sql(
            "INSERT INTO playlist_tracks VALUES (1, 'track-1', 1, '2026-01-01')"
        )
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.stamp(config, "20260724_0019")
        command.upgrade(config, "head")
    columns = {
        column["name"]
        for column in inspect(engine).get_columns("playlist_tracks")
    }
    assert {
        "title",
        "artist",
        "album",
        "album_artist",
        "track_number",
        "duration",
    } <= columns
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT spotify_track_id FROM playlist_tracks "
                "WHERE playlist_id=1"
            )
        ).scalar_one() == "track-1"
