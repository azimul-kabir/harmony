import asyncio
from types import SimpleNamespace

from app.database.models import Playlist, Song
from app.database.session import SessionLocal
from app.services.navidrome_sync_health import NavidromeSyncHealth


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
        db.add(Song(path="/music/Artist/Album/song.mp3", filename="song.mp3", artist="Artist", album="Album"))
        db.add(Playlist(spotify_id="playlist", name="Favourites"))
        db.commit()
    finally:
        db.close()


def test_sync_health_reports_matching_library_counts():
    seed_library()
    health = NavidromeSyncHealth(settings=settings(), client=FakeNavidrome())

    result = asyncio.run(health.check())

    assert result["state"] == "healthy"
    assert result["expected"] == result["actual"] == {"songs": 1, "albums": 1, "artists": 1, "playlists": 1}
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
