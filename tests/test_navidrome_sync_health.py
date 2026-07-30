import asyncio
from types import SimpleNamespace

from sqlalchemy import select

from app.database.models import Playlist, Song
from app.database.session import SessionLocal
from app.services.navidrome_sync_health import (
    NavidromeSyncHealth,
    normalize_library_path,
)


class FakeNavidrome:
    configured = True

    def __init__(self, *, stale=False):
        self.stale = stale
        self.scan_requests = 0

    async def library_songs(self):
        songs = [{"id": "remote-1", "path": "Artist/Album/song.mp3"}]
        if self.stale:
            songs.append({"id": "stale", "path": "removed.mp3"})
        return songs

    async def get_albums(self):
        return [{"id": "album-1"}]

    async def get_artists(self):
        return [{"id": "artist-1"}]

    async def get_playlists(self):
        return [{"id": "playlist-1", "name": "Favourites"}]

    async def status(self):
        return {"reachable": True, "scanning": False}

    async def start_scan(self):
        self.scan_requests += 1


class BrokenNavidrome(FakeNavidrome):
    async def library_songs(self):
        raise RuntimeError("unexpected response shape")


def settings(*, auto_reconcile=False):
    return SimpleNamespace(
        music_path="/music",
        navidrome_sync_health_auto_reconcile=auto_reconcile,
        navidrome_sync_health_enabled=True,
        navidrome_sync_health_interval_minutes=15,
    )


def seed_library():
    db = SessionLocal()
    try:
        db.add(
            Song(
                path="/music/Artist/Album/song.mp3",
                filename="song.mp3",
                artist="Artist",
                album="Album",
            )
        )
        db.add(Playlist(spotify_id="playlist", name="Favourites"))
        db.commit()
    finally:
        db.close()


def test_sync_health_reports_matching_library_counts(monkeypatch):
    monkeypatch.setattr(
        "app.services.navidrome_sync_health.os.path.isfile", lambda _: True
    )
    monkeypatch.setattr("app.services.navidrome_sync_health.os.access", lambda *_: True)
    seed_library()
    health = NavidromeSyncHealth(settings=settings(), client=FakeNavidrome())

    result = asyncio.run(health.check())

    assert result["state"] == "healthy"
    assert (
        result["expected"]
        == result["actual"]
        == {"songs": 1, "albums": 1, "artists": 1, "playlists": 1}
    )
    assert result["missing_tracks"] == 0
    assert result["stale_tracks"] == 0


def test_sync_health_requests_reconciliation_when_drift_is_detected():
    seed_library()
    client = FakeNavidrome(stale=True)
    health = NavidromeSyncHealth(settings=settings(auto_reconcile=True), client=client)

    result = asyncio.run(health.check())

    assert result["state"] == "drift"
    assert result["stale_tracks"] == 1
    assert result["reconciliation_requested"] is True
    assert client.scan_requests == 1


def test_sync_health_returns_clean_unavailable_state_for_unexpected_failures():
    health = NavidromeSyncHealth(settings=settings(), client=BrokenNavidrome())

    result = asyncio.run(health.check())

    assert result["state"] == "unavailable"
    assert result["error"] == "unexpected response shape"
    assert health._lock.acquire(blocking=False) is True
    health._lock.release()


def test_path_normalization_is_lexical_and_library_relative():
    assert (
        normalize_library_path("Artist/Album/song.mp3", "/music")
        == "artist/album/song.mp3"
    )
    assert (
        normalize_library_path("/music/Artist/Album/song.mp3", "/music")
        == "artist/album/song.mp3"
    )
    assert (
        normalize_library_path("/volume1/music/Artist/Album/song.mp3", "/music")
        == "artist/album/song.mp3"
    )
    assert (
        normalize_library_path(r"C:\\music\\Artist\\Album\\song.mp3", "/music")
        == "artist/album/song.mp3"
    )
    assert normalize_library_path(
        "Artist/Cafe%CC%81/song.mp3", "/music"
    ) == normalize_library_path("Artist/Caf%C3%A9/song.mp3", "/music")


def test_stale_id_is_recovered_and_persisted(monkeypatch):
    seed_library()
    db = SessionLocal()
    try:
        song = db.scalar(select(Song))
        song.navidrome_id = "old-id"
        db.commit()
    finally:
        db.close()
    monkeypatch.setattr(
        "app.services.navidrome_sync_health.os.path.isfile", lambda _: True
    )
    monkeypatch.setattr("app.services.navidrome_sync_health.os.access", lambda *_: True)
    result = asyncio.run(
        NavidromeSyncHealth(settings=settings(), client=FakeNavidrome()).check(
            repair_ids=True
        )
    )
    assert result["invalid_stored_navidrome_id"] == 1
    assert result["recovered_by_path"] == result["repaired_navidrome_ids"] == 1
    db = SessionLocal()
    try:
        assert db.scalar(select(Song.navidrome_id)) == "remote-1"
    finally:
        db.close()


def test_missing_file_is_separate_from_missing_in_navidrome():
    seed_library()
    result = asyncio.run(
        NavidromeSyncHealth(settings=settings(), client=FakeNavidrome()).check()
    )
    assert result["missing_on_filesystem"] == 1
    assert result["missing_from_navidrome"] == 0


def test_duplicate_remote_path_is_ambiguous_and_not_repaired(monkeypatch):
    seed_library()
    client = FakeNavidrome()

    async def duplicates():
        return [
            {"id": "one", "path": "Artist/Album/song.mp3"},
            {"id": "two", "path": "Artist/Album/song.mp3"},
        ]

    client.library_songs = duplicates
    monkeypatch.setattr(
        "app.services.navidrome_sync_health.os.path.isfile", lambda _: True
    )
    monkeypatch.setattr("app.services.navidrome_sync_health.os.access", lambda *_: True)
    result = asyncio.run(
        NavidromeSyncHealth(settings=settings(), client=client).check(repair_ids=True)
    )
    assert result["ambiguous_matches"] == 1
    assert result["duplicate_remote_paths"] == 1
    assert result["repaired_navidrome_ids"] == 0
