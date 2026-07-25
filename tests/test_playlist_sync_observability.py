import subprocess
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.database.models import SyncSource, Task
from app.database.session import SessionLocal
from app.downloaders.spotdl import SpotDLClient
from app.services import playlist_sync


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

        monkeypatch.setattr(
            playlist_sync,
            "import_playlist",
            lambda _: (_ for _ in ()).throw(
                RuntimeError("SpotDL execution timed out after 3600 seconds.")
            ),
        )

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
