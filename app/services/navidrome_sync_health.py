from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.logging import logger
from app.core.time import utcnow_naive
from app.database.models import Playlist, Song
from app.database.session import SessionLocal
from app.services.navidrome import NavidromeClient, NavidromeError


def _path_key(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip("/").casefold()


def _same_path(local_path: str, remote_path: Any, music_path: str) -> bool:
    remote = _path_key(remote_path)
    if not remote:
        return False
    local = Path(local_path)
    try:
        relative = local.resolve().relative_to(Path(music_path).resolve())
        local_key = _path_key(relative)
    except ValueError:
        local_key = _path_key(local)
    return local_key == remote or local_key.endswith(f"/{remote}") or remote.endswith(f"/{local_key}")


def _local_path_keys(local_path: str, music_path: str) -> set[str]:
    """Return the path forms Navidrome may expose for a Harmony song."""
    local = Path(local_path)
    keys = {_path_key(local)}
    try:
        keys.add(_path_key(local.resolve().relative_to(Path(music_path).resolve())))
    except ValueError:
        pass
    return {key for key in keys if key}


@dataclass(frozen=True)
class _LocalSong:
    path: str
    navidrome_id: str | None


class NavidromeSyncHealth:
    """Compare Harmony's authoritative catalog with Navidrome's current index."""

    def __init__(self, *, settings=None, client=None, session_factory=SessionLocal):
        self.settings = settings or get_settings()
        self.client = client or NavidromeClient(self.settings)
        self.session_factory = session_factory
        self._lock = threading.Lock()
        self._snapshot: dict[str, Any] | None = None

    def snapshot(self) -> dict[str, Any]:
        if self._snapshot is not None:
            return self._snapshot
        return {
            "configured": self.client.configured,
            "state": "pending" if self.client.configured else "unconfigured",
            "healthy": None,
            "checked_at": None,
            "reconciliation_requested": False,
        }

    async def check(self, *, reconcile: bool = False) -> dict[str, Any]:
        if not self.client.configured:
            self._snapshot = self.snapshot()
            return self._snapshot
        if not self._lock.acquire(blocking=False):
            return {**self.snapshot(), "state": "checking"}
        try:
            # Do not keep a SQLite session (and its read transaction) open while
            # a large remote library is paged from Navidrome.
            db = self.session_factory()
            try:
                local_songs = [
                    _LocalSong(path=song.path, navidrome_id=song.navidrome_id)
                    for song in db.scalars(
                        select(Song).where(Song.availability_status == "available")
                    ).all()
                ]
                local_playlist_names = list(db.scalars(select(Playlist.name)).all())
                expected = {
                    "songs": len(local_songs),
                    "albums": db.scalar(select(func.count(func.distinct(Song.album))).where(Song.availability_status == "available", Song.album.is_not(None))) or 0,
                    "artists": db.scalar(select(func.count(func.distinct(func.coalesce(Song.album_artist, Song.artist)))).where(Song.availability_status == "available", func.coalesce(Song.album_artist, Song.artist).is_not(None))) or 0,
                    "playlists": len(local_playlist_names),
                }
            finally:
                db.close()

            remote_songs, remote_albums, remote_artists, remote_playlists = await asyncio.gather(
                self.client.library_songs(),
                self.client.get_albums(),
                self.client.get_artists(),
                self.client.get_playlists(),
            )

            remote_ids = {str(song.get("id")) for song in remote_songs if song.get("id")}
            remote_by_path: dict[str, dict[str, Any]] = {}
            for remote_song in remote_songs:
                remote_path = _path_key(remote_song.get("path"))
                if remote_path:
                    remote_by_path[remote_path] = remote_song
            matched_remote_ids: set[str] = set()
            missing: list[_LocalSong] = []
            for song in local_songs:
                if song.navidrome_id and song.navidrome_id in remote_ids:
                    matched_remote_ids.add(song.navidrome_id)
                    continue
                match = next(
                    (remote_by_path[key] for key in _local_path_keys(song.path, self.settings.music_path) if key in remote_by_path),
                    None,
                )
                if match:
                    if match.get("id"):
                        matched_remote_ids.add(str(match["id"]))
                else:
                    missing.append(song)
            stale = [song for song in remote_songs if str(song.get("id") or "") not in matched_remote_ids]

            actual = {
                "songs": len(remote_songs),
                "albums": len(remote_albums),
                "artists": len(remote_artists),
                "playlists": len(remote_playlists),
            }
            missing_playlist_names = sorted(
                name for name in local_playlist_names
                if not any(str(item.get("name") or "").casefold() == name.casefold() for item in remote_playlists)
            )
            healthy = not missing and not stale and not missing_playlist_names and expected == actual
            requested = False
            if not healthy and (reconcile or self.settings.navidrome_sync_health_auto_reconcile):
                status = await self.client.status()
                if status.get("reachable") and not status.get("scanning"):
                    await self.client.start_scan()
                    requested = True
            self._snapshot = {
                "configured": True,
                "state": "healthy" if healthy else "drift",
                "healthy": healthy,
                "checked_at": utcnow_naive().isoformat() + "Z",
                "expected": expected,
                "actual": actual,
                "missing_tracks": len(missing),
                "stale_tracks": len(stale),
                "missing_track_samples": [song.path for song in missing[:10]],
                "stale_track_samples": [str(song.get("path") or song.get("title") or song.get("id")) for song in stale[:10]],
                "missing_playlists": missing_playlist_names[:10],
                "reconciliation_requested": requested,
            }
        except Exception as error:
            self._snapshot = {
                "configured": True, "state": "unavailable", "healthy": False,
                "checked_at": utcnow_naive().isoformat() + "Z", "error": str(error),
                "reconciliation_requested": False,
            }
            logger.warning("Navidrome sync health check failed: {}", error)
        finally:
            self._lock.release()
        return self._snapshot


class NavidromeSyncHealthScheduler:
    def __init__(self, health: NavidromeSyncHealth):
        self.health = health
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="navidrome-sync-health")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None

    def _run(self):
        while not self._stop.is_set():
            if self.health.settings.navidrome_sync_health_enabled and self.health.client.configured:
                try:
                    asyncio.run(self.health.check())
                except Exception:
                    logger.exception("Navidrome sync health scheduler iteration failed")
            minutes = max(1, int(self.health.settings.navidrome_sync_health_interval_minutes))
            self._stop.wait(minutes * 60)


navidrome_sync_health = NavidromeSyncHealth()
navidrome_sync_health_scheduler = NavidromeSyncHealthScheduler(navidrome_sync_health)
