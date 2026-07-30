from __future__ import annotations

import asyncio
import os
import posixpath
import re
import threading
import time
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.logging import logger
from app.core.time import utcnow_naive
from app.database.models import Playlist, Song
from app.database.session import SessionLocal
from app.services.navidrome import NavidromeClient


def normalize_library_path(value: Any, music_path: str, *, remote: bool = False) -> str:
    """Return a lexical, Unicode-normalized path relative to the music library.

    No filesystem resolution is used.  Navidrome commonly returns relative paths,
    while old Harmony rows may contain a host mount which is unavailable in the
    container.  In that case the configured library directory name is used as a
    conservative mount marker (``/volume1/music/A`` -> ``A``).
    """
    raw = unicodedata.normalize("NFC", unquote(str(value or ""))).replace("\\", "/")
    # Navidrome prefixes paths returned by search3 with the numeric music-folder
    # id (for example ``1:Artist/Album/song.mp3``).  It is an API namespace, not
    # part of the path mounted in either container.
    if remote:
        raw = re.sub(r"^\d+:(?:/+)?", "", raw, count=1)
    absolute = raw.startswith("/") or (len(raw) > 2 and raw[1] == ":" and raw[2] == "/")
    raw = posixpath.normpath(raw)
    if raw in {"", ".", "/"}:
        return ""
    root = unicodedata.normalize("NFC", unquote(str(music_path or ""))).replace(
        "\\", "/"
    )
    root = posixpath.normpath(root).rstrip("/")
    folded, root_folded = raw.casefold(), root.casefold()
    if folded == root_folded:
        raw = ""
    elif root and folded.startswith(root_folded + "/"):
        raw = raw[len(root) + 1 :]
    elif absolute:
        marker = PurePosixPath(root).name.casefold() if root else ""
        parts = raw.strip("/").split("/")
        indexes = [
            i for i, part in enumerate(parts) if marker and part.casefold() == marker
        ]
        # Only translate an alternate mount when the configured root marker is
        # unambiguous. Otherwise retain the absolute path and do not suffix-match.
        if len(indexes) == 1:
            raw = "/".join(parts[indexes[0] + 1 :])
        elif remote and parts and parts[0].casefold() == marker:
            raw = "/".join(parts[1:])
        else:
            raw = raw.lstrip("/")
    else:
        parts = raw.strip("/").split("/")
        marker = PurePosixPath(root).name.casefold() if root else ""
        if remote and parts and parts[0].casefold() == marker:
            parts.pop(0)
        raw = "/".join(parts)
    # Case-folding is intentional for cross-platform identity; original paths
    # remain in samples/logs for diagnostics.
    return unicodedata.normalize("NFC", raw.strip("/")).casefold()


def _same_path(local_path: str, remote_path: Any, music_path: str) -> bool:
    local = normalize_library_path(local_path, music_path)
    remote = normalize_library_path(remote_path, music_path, remote=True)
    return bool(local and local == remote)


@dataclass(frozen=True)
class _LocalSong:
    id: int
    path: str
    navidrome_id: str | None
    file_exists: bool
    title: str | None
    album: str | None
    artist: str | None


class NavidromeSyncHealth:
    """Compare Harmony's authoritative catalog with Navidrome's current index."""

    def __init__(self, *, settings=None, client=None, session_factory=SessionLocal):
        self.settings = settings or get_settings()
        self.client = client or NavidromeClient(self.settings)
        self.session_factory = session_factory
        self._lock = threading.Lock()
        self._snapshot: dict[str, Any] | None = None

    def snapshot(self) -> dict[str, Any]:
        return self._snapshot or {
            "configured": self.client.configured,
            "state": "pending" if self.client.configured else "unconfigured",
            "healthy": None,
            "checked_at": None,
            "reconciliation_requested": False,
        }

    def _read_local(self):
        db = self.session_factory()
        try:
            rows = db.scalars(
                select(Song).where(Song.availability_status == "available")
            ).all()
            songs = [
                _LocalSong(
                    s.id,
                    s.path,
                    s.navidrome_id,
                    os.path.isfile(s.path) and os.access(s.path, os.R_OK),
                    s.title,
                    s.album,
                    s.artist,
                )
                for s in rows
            ]
            playlists = list(db.scalars(select(Playlist.name)).all())
            expected = {
                "songs": len(songs),
                "albums": db.scalar(
                    select(func.count(func.distinct(Song.album))).where(
                        Song.availability_status == "available", Song.album.is_not(None)
                    )
                )
                or 0,
                "artists": db.scalar(
                    select(
                        func.count(
                            func.distinct(func.coalesce(Song.album_artist, Song.artist))
                        )
                    ).where(
                        Song.availability_status == "available",
                        func.coalesce(Song.album_artist, Song.artist).is_not(None),
                    )
                )
                or 0,
                "playlists": len(playlists),
            }
            return songs, playlists, expected
        finally:
            db.close()

    def _persist_repairs(self, repairs: dict[int, str]) -> int:
        if not repairs:
            return 0
        db = self.session_factory()
        try:
            repaired = 0
            for song_id, remote_id in repairs.items():
                song = db.get(Song, song_id)
                if song and song.navidrome_id != remote_id:
                    song.navidrome_id = remote_id
                    repaired += 1
            db.commit()
            return repaired
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def check(
        self, *, repair_ids: bool = False, reconcile: bool = False
    ) -> dict[str, Any]:
        # ``reconcile`` remains accepted for API compatibility, but the bounded
        # workflow lives in reconcile() so no lock/session is held during a scan.
        if reconcile:
            return await self.reconcile()
        if not self.client.configured:
            self._snapshot = self.snapshot()
            return self._snapshot
        if not self._lock.acquire(blocking=False):
            return {**self.snapshot(), "state": "checking"}
        try:
            local_songs, local_playlists, expected = self._read_local()
            (
                remote_songs,
                remote_albums,
                remote_artists,
                remote_playlists,
            ) = await asyncio.gather(
                self.client.library_songs(),
                self.client.get_albums(),
                self.client.get_artists(),
                self.client.get_playlists(),
            )
            remote_by_id = {str(s["id"]): s for s in remote_songs if s.get("id")}
            local_paths: dict[str, list[_LocalSong]] = defaultdict(list)
            remote_paths: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for song in local_songs:
                key = normalize_library_path(song.path, self.settings.music_path)
                if key:
                    local_paths[key].append(song)
            for song in remote_songs:
                key = normalize_library_path(
                    song.get("path"), self.settings.music_path, remote=True
                )
                if key:
                    remote_paths[key].append(song)

            duplicate_local = {k: v for k, v in local_paths.items() if len(v) > 1}
            duplicate_remote = {k: v for k, v in remote_paths.items() if len(v) > 1}
            matched_remote: set[str] = set()
            missing: list[_LocalSong] = []
            invalid_ids: list[_LocalSong] = []
            inconsistent_ids: list[_LocalSong] = []
            recovered: list[_LocalSong] = []
            ambiguous: list[_LocalSong] = []
            repairs: dict[int, str] = {}
            matched_by_id = 0
            mismatch_diagnostics: list[dict[str, Any]] = []
            for song in local_songs:
                stored = str(song.navidrome_id) if song.navidrome_id else None
                if stored and stored in remote_by_id:
                    remote_song = remote_by_id[stored]
                    if _same_path(song.path, remote_song.get("path"), self.settings.music_path):
                        matched_remote.add(stored)
                        matched_by_id += 1
                        continue
                    if len(mismatch_diagnostics) < 10:
                        mismatch_diagnostics.append(
                            self._diagnostic(song, remote_song, "stored_id_path_mismatch")
                        )
                    inconsistent_ids.append(song)
                elif stored:
                    invalid_ids.append(song)
                key = normalize_library_path(song.path, self.settings.music_path)
                candidates = (
                    remote_paths.get(key, [])
                    if key and key not in duplicate_local
                    else []
                )
                if len(candidates) == 1:
                    remote_id = str(candidates[0].get("id") or "")
                    if remote_id:
                        matched_remote.add(remote_id)
                        recovered.append(song)
                        repairs[song.id] = remote_id
                    else:
                        missing.append(song)
                elif len(candidates) > 1 or (
                    key in duplicate_local and key in remote_paths
                ):
                    ambiguous.append(song)
                else:
                    missing.append(song)
            repaired = self._persist_repairs(repairs) if repair_ids else 0
            stale = [
                s
                for s in remote_songs
                if str(s.get("id") or "") not in matched_remote
                and normalize_library_path(
                    s.get("path"), self.settings.music_path, remote=True
                )
                not in duplicate_remote
            ]
            missing_fs = [s for s in local_songs if not s.file_exists]
            missing_playlists = sorted(
                name
                for name in local_playlists
                if not any(
                    str(p.get("name") or "").casefold() == name.casefold()
                    for p in remote_playlists
                )
            )
            actual = {
                "songs": len(remote_songs),
                "albums": len(remote_albums),
                "artists": len(remote_artists),
                "playlists": len(remote_playlists),
            }
            healthy = (
                not any(
                    (
                        missing,
                        stale,
                        missing_fs,
                        ambiguous,
                        duplicate_local,
                        duplicate_remote,
                        missing_playlists,
                    )
                )
                and expected == actual
            )
            result = {
                "configured": True,
                "state": "healthy" if healthy else "drift",
                "healthy": healthy,
                "checked_at": utcnow_naive().isoformat() + "Z",
                "expected": expected,
                "actual": actual,
                "missing_from_navidrome": len(missing),
                "stale_in_navidrome": len(stale),
                "missing_on_filesystem": len(missing_fs),
                "invalid_stored_navidrome_id": len(invalid_ids),
                "inconsistent_stored_navidrome_id": len(inconsistent_ids),
                "recovered_by_path": len(recovered),
                "ambiguous_matches": len(ambiguous),
                "duplicate_local_paths": len(duplicate_local),
                "duplicate_remote_paths": len(duplicate_remote),
                "missing_tracks": len(missing),
                "stale_tracks": len(stale),
                "missing_playlists": missing_playlists[:10],
                "missing_track_samples": [s.path for s in missing[:10]],
                "stale_track_samples": [
                    str(s.get("path") or s.get("id")) for s in stale[:10]
                ],
                "missing_on_filesystem_samples": [s.path for s in missing_fs[:10]],
                "ambiguous_match_samples": [s.path for s in ambiguous[:10]],
                "repaired_navidrome_ids": repaired,
                "reconciliation_requested": False,
            }
            # Add unpaired samples after the more useful stored-ID inconsistencies.
            for song in missing:
                if len(mismatch_diagnostics) >= 10:
                    break
                mismatch_diagnostics.append(
                    self._diagnostic(song, None, "no_exact_path_match")
                )
            result["mismatch_diagnostics"] = mismatch_diagnostics
            logger.info(
                "Navidrome health local={} remote={} id_matches={} path_matches={} invalid_ids={} ambiguous={} missing={} stale={} missing_files={} local_root={} remote_root=library-relative",
                len(local_songs),
                len(remote_songs),
                matched_by_id,
                len(recovered),
                len(invalid_ids),
                len(ambiguous),
                len(missing),
                len(stale),
                len(missing_fs),
                self.settings.music_path,
            )
            logger.debug(
                "Navidrome health mismatch_diagnostics={} stale_samples={}",
                mismatch_diagnostics,
                result["stale_track_samples"],
            )
            if not healthy and self.settings.navidrome_sync_health_auto_reconcile:
                status = await self.client.status()
                if status.get("reachable") and not status.get("scanning"):
                    await self.client.start_scan()
                    result["reconciliation_requested"] = True
            self._snapshot = result
        except Exception as error:  # noqa: BLE001
            self._snapshot = {
                "configured": True,
                "state": "unavailable",
                "healthy": False,
                "checked_at": utcnow_naive().isoformat() + "Z",
                "error": str(error),
                "reconciliation_requested": False,
            }
            logger.warning("Navidrome sync health check failed: {}", error)
        finally:
            self._lock.release()
        return self._snapshot

    def _diagnostic(
        self,
        local: _LocalSong,
        remote: dict[str, Any] | None,
        reason: str,
    ) -> dict[str, Any]:
        """Build a capped, structured record without exposing credentials."""
        remote = remote or {}
        return {
            "reason": reason,
            "harmony": {
                "id": local.id,
                "path": local.path,
                "navidrome_id": local.navidrome_id,
                "path_exists": local.file_exists,
                "normalized_path": normalize_library_path(
                    local.path, self.settings.music_path
                ),
                "title": local.title,
                "album": local.album,
                "artist": local.artist,
            },
            "navidrome": {
                "endpoint": "search3",
                "id": remote.get("id"),
                "path": remote.get("path"),
                "normalized_path": normalize_library_path(
                    remote.get("path"), self.settings.music_path, remote=True
                ),
                "title": remote.get("title"),
                "album": remote.get("album"),
                "artist": remote.get("artist"),
                "parent_id": remote.get("parent"),
                "music_folder_id": remote.get("musicFolderId"),
            },
            "stored_id_matches": bool(
                local.navidrome_id
                and str(local.navidrome_id) == str(remote.get("id") or "")
            ),
            "normalized_path_matches": _same_path(
                local.path, remote.get("path"), self.settings.music_path
            ),
        }

    async def reconcile(self, *, full_scan: bool = False) -> dict[str, Any]:
        started_at = time.monotonic()
        before = await self.check(repair_ids=False)
        scan = {
            "accepted": False,
            "started": False,
            "completed": False,
            "timed_out": False,
            "warnings": [],
        }
        status_before = await self.client.status()
        if not status_before.get("reachable"):
            scan["warnings"].append(
                status_before.get("error") or "Navidrome is unavailable."
            )
        else:
            response = await self.client.start_scan(full_scan=full_scan)
            scan["accepted"] = bool(response.get("accepted", True))
            scan["started"] = bool(response.get("scanning"))
            deadline = time.monotonic() + max(
                1.0,
                float(
                    getattr(
                        self.settings,
                        "navidrome_sync_health_full_scan_timeout_seconds"
                        if full_scan
                        else "navidrome_sync_health_scan_timeout_seconds",
                        600 if full_scan else 240,
                    )
                ),
            )
            poll = max(
                0.05,
                float(getattr(self.settings, "navidrome_sync_health_poll_seconds", 1)),
            )
            old_last = status_before.get("last_scan")
            while time.monotonic() < deadline:
                status = await self.client.status()
                if not status.get("reachable"):
                    scan["warnings"].append(
                        status.get("error") or "Navidrome became unavailable."
                    )
                    break
                scan["started"] = scan["started"] or bool(status.get("scanning"))
                changed = (
                    status.get("last_scan") is not None
                    and status.get("last_scan") != old_last
                )
                if not status.get("scanning") and (scan["started"] or changed):
                    scan["completed"] = True
                    break
                await asyncio.sleep(poll)
            else:
                scan["timed_out"] = True
                scan["warnings"].append(
                    "Timed out waiting for Navidrome to start and finish its scan."
                )
        after = await self.check(repair_ids=True)
        resolved = {
            key: max(0, int(before.get(key, 0)) - int(after.get(key, 0)))
            for key in ("missing_tracks", "stale_tracks", "invalid_stored_navidrome_id")
        }
        scan["elapsed_seconds"] = round(time.monotonic() - started_at, 3)
        logger.info(
            "Navidrome reconciliation completed={} timed_out={} repaired={} before_missing={} after_missing={} elapsed={}",
            scan["completed"],
            scan["timed_out"],
            after.get("repaired_navidrome_ids", 0),
            before.get("missing_tracks"),
            after.get("missing_tracks"),
            scan["elapsed_seconds"],
        )
        return {
            "pre_scan_health": before,
            "scan": scan,
            "post_scan_health": after,
            "repaired_navidrome_ids": after.get("repaired_navidrome_ids", 0),
            "resolved": resolved,
            "remaining_drift": {
                "missing_tracks": after.get("missing_tracks", 0),
                "stale_tracks": after.get("stale_tracks", 0),
                "ambiguous_matches": after.get("ambiguous_matches", 0),
            },
            **after,
        }


class NavidromeSyncHealthScheduler:
    def __init__(self, health):
        self.health, self._stop, self._thread = health, threading.Event(), None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="navidrome-sync-health"
        )
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None

    def _run(self):
        while not self._stop.is_set():
            if (
                self.health.settings.navidrome_sync_health_enabled
                and self.health.client.configured
            ):
                try:
                    asyncio.run(self.health.check())
                except Exception:  # noqa: BLE001
                    logger.exception("Navidrome sync health scheduler iteration failed")
            self._stop.wait(
                max(1, int(self.health.settings.navidrome_sync_health_interval_minutes))
                * 60
            )


navidrome_sync_health = NavidromeSyncHealth()
navidrome_sync_health_scheduler = NavidromeSyncHealthScheduler(navidrome_sync_health)
