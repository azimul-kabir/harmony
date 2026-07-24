import asyncio
from types import SimpleNamespace

from app.database.models import Playlist, SyncSource
from app.database.session import SessionLocal
from app.domain.task import TaskType
from app.services import navidrome_playlist_sync
from app.services.navidrome_playlist_sync import (
    NavidromePlaylistReimportCoordinator,
)
from app.services.task_service import create_task


def _settings(**overrides):
    values = {
        "navidrome_url": "http://navidrome:4533",
        "navidrome_username": "harmony",
        "navidrome_password": "secret",
        "navidrome_direct_playlist_sync_enabled": False,
        "navidrome_playlist_reimport_enabled": True,
        "navidrome_playlist_reimport_debounce_seconds": 0,
        "navidrome_playlist_reimport_poll_seconds": 0.01,
        "navidrome_playlist_reimport_scan_timeout_seconds": 2,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _playlist_sync_task(db):
    source = SyncSource(
        type="playlist",
        spotify_id="playlist-1",
        spotify_url="https://open.spotify.com/playlist/playlist-1",
        name="Road Trip",
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    playlist = Playlist(
        spotify_id=source.spotify_id,
        name=source.name,
        track_count=2,
    )
    db.add(playlist)
    db.commit()
    task = create_task(
        db=db,
        name=source.name,
        spotify_url=source.spotify_url,
        source_id=source.id,
        task_type=TaskType.PLAYLIST_SYNC,
        total_items=2,
    )
    return task, playlist


def test_reconcile_scans_rewrites_then_scans_again(monkeypatch):
    events = []

    class Client:
        async def status(self):
            events.append("status")
            return {"reachable": True, "scanning": False}

        async def start_scan(self, *, full_scan=False):
            assert full_scan is False
            events.append("scan")
            return {"accepted": True, "scanning": True}

    monkeypatch.setattr(
        navidrome_playlist_sync,
        "export_m3u",
        lambda db, playlist: events.append(f"export:{playlist.id}") or 2,
    )
    db = SessionLocal()
    try:
        task, playlist = _playlist_sync_task(db)
        coordinator = NavidromePlaylistReimportCoordinator(
            settings=_settings(),
            client_factory=Client,
        )

        assert asyncio.run(coordinator.reconcile({task.id})) is True
        assert events == [
            "status",
            "scan",
            "status",
            f"export:{playlist.id}",
            "status",
            "scan",
            "status",
        ]
    finally:
        db.close()


def test_reconcile_is_disabled_without_credentials():
    coordinator = NavidromePlaylistReimportCoordinator(
        settings=_settings(navidrome_password=""),
    )

    assert coordinator.enabled is False
    assert coordinator.schedule(1) is False
    assert asyncio.run(coordinator.reconcile({1})) is False


def test_successful_direct_reconcile_skips_second_scan(monkeypatch):
    events = []

    class Client:
        async def status(self):
            events.append("status")
            return {"reachable": True, "scanning": False}

        async def start_scan(self, *, full_scan=False):
            events.append("scan")
            return {"accepted": True}

    class Direct:
        def __init__(self, **kwargs):
            pass

        async def reconcile(self, playlist_id):
            events.append(f"direct:{playlist_id}")
            return SimpleNamespace(
                playlist_id=playlist_id,
                track_count=2,
            )

    monkeypatch.setattr(navidrome_playlist_sync, "NavidromeDirectPlaylistSync", Direct)
    monkeypatch.setattr(
        navidrome_playlist_sync,
        "export_m3u",
        lambda db, playlist: events.append(f"export:{playlist.id}") or 2,
    )
    db = SessionLocal()
    try:
        task, playlist = _playlist_sync_task(db)
        coordinator = NavidromePlaylistReimportCoordinator(
            settings=_settings(
                navidrome_direct_playlist_sync_enabled=True
            ),
            client_factory=Client,
        )

        assert asyncio.run(coordinator.reconcile({task.id})) is True
        assert events == [
            "status",
            "scan",
            "status",
            f"export:{playlist.id}",
            f"direct:{playlist.id}",
        ]
    finally:
        db.close()
