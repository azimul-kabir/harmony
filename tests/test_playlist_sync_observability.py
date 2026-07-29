import subprocess
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.database.models import SyncSource, Task
from app.database.session import SessionLocal
from app.downloaders.spotdl import SpotDLClient
from app.services import playlist_sync
from app.domain.track import Track


def test_spotdl_playlist_uses_configured_large_playlist_timeout(monkeypatch):
    client = SpotDLClient()
    monkeypatch.setattr(
        client.settings,
        "spotify_playlist_metadata_timeout_seconds",
        4200,
    )
    observed = {}

    monkeypatch.setattr(client, "validate_executable", lambda: "spotdl")

    def run(args, timeout):
        observed["timeout"] = timeout
        return subprocess.CompletedProcess(args, 1, "", "provider failed")

    monkeypatch.setattr(client, "_run", run)

    with pytest.raises(RuntimeError, match="provider failed"):
        client.playlist("https://open.spotify.com/playlist/large")
    assert observed["timeout"] == 4200


def test_spotdl_preflight_reports_invalid_runtime_path(tmp_path):
    client = SpotDLClient()
    client.settings = SimpleNamespace(spotdl_path=str(tmp_path / "missing-spotdl"))

    with pytest.raises(RuntimeError, match="SPOTDL_PATH"):
        client.validate_executable()


def test_spotdl_run_uses_writable_xdg_config_directory(monkeypatch, tmp_path):
    client = SpotDLClient()
    client.settings = SimpleNamespace(spotdl_path="spotdl")
    config_dir = tmp_path / "spotdl-config"
    observed = {}

    monkeypatch.setenv("HOME", "/")
    monkeypatch.setenv("HARMONY_SPOTDL_CONFIG_DIR", str(config_dir))

    def run(command, **kwargs):
        observed.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)

    client._run(["--version"])

    assert config_dir.is_dir()
    assert observed["env"]["HOME"] == "/tmp"
    assert observed["env"]["XDG_CONFIG_HOME"] == str(config_dir)
    assert observed["env"]["HARMONY_SPOTDL_CONFIG_DIR"] == str(config_dir)


def test_playlist_sync_persists_actionable_metadata_timeout(monkeypatch):
    db = SessionLocal()
    try:
        source = SyncSource(
            type="playlist",
            spotify_id="large-playlist",
            spotify_url="https://open.spotify.com/playlist/large-playlist",
            name="Liked Songs",
        )
        db.add(source)
        db.commit()
        db.refresh(source)

        class TimeoutReader:
            def __init__(self, _url):
                pass

            def metadata(self):
                raise RuntimeError("SpotDL execution timed out after 3600 seconds.")

        monkeypatch.setattr(playlist_sync, "UnofficialSpotifyPlaylistReader", TimeoutReader)

        task = playlist_sync.sync_playlist(db, source)
        saved = db.scalar(select(Task).where(Task.id == task.id))

        assert saved.status == "failed"
        assert saved.error_code == "playlist_metadata_timeout"
        assert "Settings → Downloads" in saved.error_summary
        assert saved.started_at is not None
        assert saved.completed_at is not None
        assert saved.total_items == 0
    finally:
        db.close()


def test_playlist_sync_queues_each_discovery_batch_immediately(monkeypatch):
    db = SessionLocal()
    try:
        source = SyncSource(
            type="playlist",
            spotify_id="large-playlist-batched",
            spotify_url="https://open.spotify.com/playlist/large-playlist-batched",
            name="Fetching Playlist Data...",
        )
        db.add(source)
        db.commit()
        db.refresh(source)
        events = []

        class BatchReader:
            def __init__(self, _url):
                pass

            def metadata(self):
                return SimpleNamespace(name="Liked Songs")

            def batches(self):
                for start in (0, 50):
                    yield [
                        Track(
                            title=f"Song {position}",
                            artist="Artist",
                            spotify_track_id=f"track-{position}",
                            spotify_url=f"https://open.spotify.com/track/{position}",
                        )
                        for position in range(start, start + 50)
                    ]

        monkeypatch.setattr(playlist_sync, "UnofficialSpotifyPlaylistReader", BatchReader)
        monkeypatch.setattr(playlist_sync, "_can_enqueue", lambda **_: True)
        monkeypatch.setattr(
            playlist_sync,
            "enqueue_tracks_bulk",
            lambda db, tracks, task_id: events.append(len(tracks)),
        )
        monkeypatch.setattr(playlist_sync, "export_m3u", lambda *_args, **_kwargs: 0)

        task = playlist_sync.sync_playlist(db, source)

        assert events == [50, 50]
        assert task.total_items == 100
        assert task.current_item == "100 downloads queued; waiting for workers…"
        assert source.name == "Liked Songs"
    finally:
        db.close()
