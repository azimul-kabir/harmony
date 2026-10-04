"""Rebuild Harmony's persisted Navidrome song and playlist references.

``songs.navidrome_id`` and ``playlists.navidrome_playlist_id`` are external
references, not identities.  Navidrome can re-encode them (0.64 migrated every
ID to canonical Base62), so Harmony remaps them from stable attributes it
already owns: library path, MusicBrainz recording ID, ISRC, and normalized
metadata.  Reconciliation only reads from Navidrome and only updates those two
columns; it never creates, deletes, or merges Harmony songs or playlists.
"""

from __future__ import annotations

import asyncio
import json
import posixpath
import re
import threading
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import logger
from app.core.time import utcnow_naive
from app.database.models import AppSetting, Playlist, Song
from app.database.session import SessionLocal
from app.services.library_paths import sanitize_path_component
from app.services.navidrome import (
    NavidromeClient,
    NavidromeError,
    navidrome_id_scheme,
    parse_server_version,
)
from app.services.playlist_manager import playlist_file_path
from app.services.settings_service import INTERNAL_SETTING_CATEGORY

STATE_KEY = "navidrome_id_reconciliation"
# Stored song IDs probed after an unrecognized Navidrome version change.
PROBE_SAMPLE_SIZE = 5
DURATION_TOLERANCE_SECONDS = 2.0


def _text(value: Any) -> str:
    return unicodedata.normalize("NFC", str(value or "")).strip().casefold()


def _normalize_track_filename(path: str) -> str:
    """Canonicalize ``TT - title`` and Navidrome's ``DD-TT - title`` prefixes."""
    directory, separator, filename = path.rpartition("/")
    filename = re.sub(r"^(?:\d{2}-)?(\d{2})\s*-\s*", r"\1 - ", filename, count=1)
    return f"{directory}{separator}{filename}"


def normalize_library_path(value: Any, music_path: str, *, remote: bool = False) -> str:
    """Return a lexical, Unicode-normalized path relative to the music library.

    Navidrome reports library-relative paths (optionally prefixed with its
    numeric music-folder ID) that may be synthesized from unsanitized tags,
    while Harmony stores absolute container paths.  No filesystem access is
    used, so a temporarily unavailable mount cannot change the result.
    """
    raw = unicodedata.normalize("NFC", unquote(str(value or ""))).replace("\\", "/")
    if remote:
        raw = re.sub(r"^\d+:(?:/+)?", "", raw, count=1)
        if any(part in {".", ".."} for part in raw.split("/")):
            return ""
    absolute = raw.startswith("/") or (len(raw) > 2 and raw[1] == ":" and raw[2] == "/")
    raw = posixpath.normpath(raw)
    if raw in {"", ".", "/"}:
        return ""
    root = unicodedata.normalize("NFC", unquote(str(music_path or ""))).replace("\\", "/")
    root = posixpath.normpath(root).rstrip("/")
    folded, root_folded = raw.casefold(), root.casefold()
    marker = PurePosixPath(root).name.casefold() if root else ""
    parts = raw.strip("/").split("/")
    if folded == root_folded:
        raw = ""
    elif root and folded.startswith(root_folded + "/"):
        raw = raw[len(root) + 1 :]
    elif absolute:
        # Translate an alternate host mount only when the library directory
        # name appears exactly once (``/volume1/music/A`` -> ``A``).
        indexes = [i for i, part in enumerate(parts) if marker and part.casefold() == marker]
        if len(indexes) == 1:
            raw = "/".join(parts[indexes[0] + 1 :])
        elif remote and parts and parts[0].casefold() == marker:
            raw = "/".join(parts[1:])
        else:
            raw = raw.lstrip("/")
    else:
        if remote and parts and parts[0].casefold() == marker:
            parts.pop(0)
        raw = "/".join(parts)
    if remote:
        raw = "/".join(sanitize_path_component(part) for part in raw.split("/"))
    normalized = unicodedata.normalize("NFC", raw.strip("/")).casefold()
    return _normalize_track_filename(normalized)


def _remote_isrcs(song: dict[str, Any]) -> set[str]:
    value = song.get("isrc")
    values = value if isinstance(value, list) else [value]
    return {str(item).strip().upper() for item in values if item and str(item).strip()}


def _durations_compatible(local: float | None, remote: Any) -> bool:
    try:
        return local is None or remote is None or abs(float(local) - float(remote)) <= DURATION_TOLERANCE_SECONDS
    except (TypeError, ValueError):
        return True


@dataclass(frozen=True)
class _LocalSong:
    id: int
    path: str
    navidrome_id: str | None
    title: str | None
    artist: str | None
    album: str | None
    duration: float | None
    isrc: str | None
    musicbrainz_recording_id: str | None


@dataclass(frozen=True)
class _LocalPlaylist:
    id: int
    name: str
    navidrome_playlist_id: str | None


def _empty_counts() -> dict[str, int]:
    return {"checked": 0, "unchanged": 0, "updated": 0, "unresolved": 0, "skipped": 0}


class _Matcher:
    """Assign each remote ID to at most one local record, tier by tier."""

    def __init__(self, remote_ids: Iterable[str]) -> None:
        self.remote_ids = set(remote_ids)
        self.claimed: set[str] = set()
        self.assignments: dict[int, str] = {}
        self.methods: dict[str, int] = defaultdict(int)

    def keep(self, local_id: int, remote_id: str) -> None:
        self.claimed.add(remote_id)
        self.assignments[local_id] = remote_id

    def tier(
        self,
        name: str,
        pending: list,
        local_key: Callable[[Any], Hashable | None],
        remote_index: dict[Hashable, list[dict[str, Any]]],
        accept: Callable[[Any, dict[str, Any]], bool] = lambda local, remote: True,
    ) -> list:
        """Match unique local keys to unique, unclaimed remote candidates."""
        keys = {item.id: local_key(item) for item in pending}
        key_counts: dict[Hashable, int] = defaultdict(int)
        for key in keys.values():
            if key:
                key_counts[key] += 1
        remaining = []
        for item in pending:
            key = keys[item.id]
            # Two local records sharing a key are ambiguous; leave both.
            candidates = (
                [
                    remote
                    for remote in remote_index.get(key, [])
                    if str(remote["id"]) not in self.claimed and accept(item, remote)
                ]
                if key and key_counts[key] == 1
                else []
            )
            if len(candidates) == 1:
                self.keep(item.id, str(candidates[0]["id"]))
                self.methods[name] += 1
            else:
                remaining.append(item)
        return remaining


class NavidromeIdReconciler:
    def __init__(
        self,
        *,
        settings=None,
        client_factory: Callable[[], NavidromeClient] = NavidromeClient,
        session_factory=SessionLocal,
    ) -> None:
        self.settings = settings or get_settings()
        self.client_factory = client_factory
        self.session_factory = session_factory
        self._lock = threading.Lock()

    # -- persisted state -------------------------------------------------

    def _read_state(self) -> dict[str, Any]:
        db = self.session_factory()
        try:
            row = db.get(AppSetting, STATE_KEY)
            try:
                value = json.loads(row.value) if row else {}
            except ValueError:
                value = {}
            return value if isinstance(value, dict) else {}
        finally:
            db.close()

    def _write_state(self, db, state: dict[str, Any]) -> None:
        row = db.get(AppSetting, STATE_KEY)
        value = json.dumps(state, sort_keys=True)
        if row is None:
            db.add(AppSetting(key=STATE_KEY, value=value, type="json", category=INTERNAL_SETTING_CATEGORY))
        else:
            row.value = value

    def _record_version(self, server_version: str | None) -> None:
        db = self.session_factory()
        try:
            state = {
                **self._read_state(),
                "server_version": server_version,
                "id_scheme": navidrome_id_scheme(server_version),
            }
            self._write_state(db, state)
            db.commit()
        finally:
            db.close()

    def _persisted_song_ids(self, limit: int | None = None) -> list[str]:
        db = self.session_factory()
        try:
            query = select(Song.navidrome_id).where(Song.navidrome_id.is_not(None)).order_by(Song.id)
            if limit is not None:
                query = query.limit(limit)
            return [str(value) for value in db.scalars(query).all()]
        finally:
            db.close()

    def _has_persisted_ids(self) -> bool:
        db = self.session_factory()
        try:
            return bool(
                db.scalar(select(Song.id).where(Song.navidrome_id.is_not(None)).limit(1))
                or db.scalar(select(Playlist.id).where(Playlist.navidrome_playlist_id.is_not(None)).limit(1))
            )
        finally:
            db.close()

    # -- automatic detection ---------------------------------------------

    async def reconcile_if_needed(self, client: NavidromeClient | None = None) -> dict[str, Any] | None:
        """Reconcile once when the connected server's ID format has changed.

        Runs when Navidrome crosses into a different known ID scheme (0.64), or
        when any version change leaves sampled persisted IDs unresolvable.  A
        server that keeps its version, or keeps resolving stored IDs, is left
        untouched.
        """
        client = client or self.client_factory()
        if not client.configured:
            return None
        status = await client.status()
        if not status.get("reachable") or status.get("scanning"):
            return None
        current_version = status.get("server_version")
        if parse_server_version(current_version) is None:
            return None
        state = await asyncio.to_thread(self._read_state)
        previous_version = state.get("server_version")
        if previous_version == current_version:
            return None
        if not await asyncio.to_thread(self._has_persisted_ids):
            await asyncio.to_thread(self._record_version, current_version)
            return None

        current_scheme = navidrome_id_scheme(current_version)
        previous_scheme = state.get("id_scheme")
        if previous_scheme is None:
            # IDs persisted before tracking began predate v3, i.e. pre-0.64.
            previous_scheme = "legacy"
        reason = None
        if previous_scheme != current_scheme:
            reason = f"Navidrome ID scheme changed from {previous_scheme} to {current_scheme}"
        else:
            sample = await asyncio.to_thread(self._persisted_song_ids, PROBE_SAMPLE_SIZE)
            try:
                for song_id in sample:
                    if not await client.song_exists(song_id):
                        reason = f"stored Navidrome IDs no longer resolve on {current_version}"
                        break
            except NavidromeError as error:
                logger.warning("Could not verify persisted Navidrome IDs: {}", error)
                return None
        if reason is None:
            await asyncio.to_thread(self._record_version, current_version)
            logger.info(
                "Navidrome version changed from {} to {}; persisted IDs still resolve.",
                previous_version,
                current_version,
            )
            return None
        logger.info("Reconciling persisted Navidrome IDs: {}.", reason)
        return await self.reconcile(trigger="automatic", client=client)

    # -- reconciliation --------------------------------------------------

    def _read_local(self) -> tuple[list[_LocalSong], list[_LocalPlaylist]]:
        db = self.session_factory()
        try:
            songs = [
                _LocalSong(
                    song.id,
                    song.path,
                    song.navidrome_id,
                    song.title,
                    song.artist,
                    song.album,
                    song.duration,
                    song.isrc,
                    song.musicbrainz_recording_id,
                )
                for song in db.scalars(select(Song).order_by(Song.id)).all()
            ]
            playlists = [
                _LocalPlaylist(playlist.id, playlist.name, playlist.navidrome_playlist_id)
                for playlist in db.scalars(select(Playlist).order_by(Playlist.id)).all()
            ]
            return songs, playlists
        finally:
            db.close()

    def _match_songs(
        self, local: list[_LocalSong], remote: list[dict[str, Any]]
    ) -> tuple[dict[int, str], dict[str, int]]:
        music_path = self.settings.music_path
        remote = [song for song in remote if song.get("id")]
        remote_by_id = {str(song["id"]): song for song in remote}
        local_by_path: dict[str, list[int]] = defaultdict(list)
        for song in local:
            key = normalize_library_path(song.path, music_path)
            if key:
                local_by_path[key].append(song.id)
        matcher = _Matcher(remote_by_id)
        pending = []
        for song in local:
            stored = str(song.navidrome_id) if song.navidrome_id else None
            remote_song = remote_by_id.get(stored) if stored else None
            # A stored ID is kept unless Navidrome now reports it for a
            # different Harmony file (reused or re-encoded IDs).
            owners = (
                local_by_path.get(normalize_library_path(remote_song.get("path"), music_path, remote=True), [])
                if remote_song
                else []
            )
            contradicted = len(owners) == 1 and owners[0] != song.id
            if remote_song and not contradicted and stored not in matcher.claimed:
                matcher.keep(song.id, stored)
            else:
                pending.append(song)

        by_path: dict[Hashable, list] = defaultdict(list)
        by_mbid: dict[Hashable, list] = defaultdict(list)
        by_isrc: dict[Hashable, list] = defaultdict(list)
        by_metadata: dict[Hashable, list] = defaultdict(list)
        for song in remote:
            path = normalize_library_path(song.get("path"), music_path, remote=True)
            if path:
                by_path[path].append(song)
            if song.get("musicBrainzId"):
                by_mbid[_text(song["musicBrainzId"])].append(song)
            for isrc in _remote_isrcs(song):
                by_isrc[isrc].append(song)
            if song.get("title") and song.get("artist"):
                by_metadata[(_text(song["title"]), _text(song["artist"]), _text(song.get("album")))].append(song)

        pending = matcher.tier("path", pending, lambda s: normalize_library_path(s.path, music_path) or None, by_path)
        pending = matcher.tier("musicbrainz", pending, lambda s: _text(s.musicbrainz_recording_id) or None, by_mbid)
        pending = matcher.tier("isrc", pending, lambda s: (s.isrc or "").strip().upper() or None, by_isrc)
        matcher.tier(
            "metadata",
            pending,
            lambda s: (_text(s.title), _text(s.artist), _text(s.album)) if s.title and s.artist else None,
            by_metadata,
            accept=lambda s, r: _durations_compatible(s.duration, r.get("duration")),
        )
        return matcher.assignments, dict(matcher.methods)

    def _match_playlists(
        self, local: list[_LocalPlaylist], remote: list[dict[str, Any]]
    ) -> dict[int, str]:
        remote = [playlist for playlist in remote if playlist.get("id")]
        matcher = _Matcher(str(playlist["id"]) for playlist in remote)
        pending = []
        for playlist in local:
            stored = playlist.navidrome_playlist_id
            if stored and stored in matcher.remote_ids and stored not in matcher.claimed:
                matcher.keep(playlist.id, stored)
            else:
                pending.append(playlist)
        # Navidrome names imported playlists after Harmony's M3U file.
        by_name: dict[Hashable, list] = defaultdict(list)
        for playlist in remote:
            by_name[_text(playlist.get("name"))].append(playlist)
        matcher.tier("name", pending, lambda p: _text(playlist_file_path(p.name).stem) or None, by_name)
        return matcher.assignments

    @staticmethod
    def _summarize(
        items: list,
        stored: Callable[[Any], str | None],
        assignments: dict[int, str],
    ) -> tuple[dict[str, int], dict[int, str | None]]:
        counts = _empty_counts()
        changes: dict[int, str | None] = {}
        for item in items:
            counts["checked"] += 1
            old, new = stored(item), assignments.get(item.id)
            if new is not None and new == old:
                counts["unchanged"] += 1
            elif new is not None:
                counts["updated"] += 1
                changes[item.id] = new
            elif old:
                # A stale ID that cannot be remapped is cleared; the record
                # itself stays intact and a later run can bind it again.
                counts["unresolved"] += 1
                changes[item.id] = None
            else:
                counts["skipped"] += 1
        return counts, changes

    def _apply(
        self,
        song_changes: dict[int, str | None],
        playlist_changes: dict[int, str | None],
        state: dict[str, Any],
    ) -> None:
        db = self.session_factory()
        try:
            # Clear first so a remapped ID can move between records without
            # tripping the unique indexes mid-update.
            if song_changes:
                for song in db.scalars(select(Song).where(Song.id.in_(list(song_changes)))).all():
                    song.navidrome_id = None
            if playlist_changes:
                for playlist in db.scalars(select(Playlist).where(Playlist.id.in_(list(playlist_changes)))).all():
                    playlist.navidrome_playlist_id = None
            db.flush()
            new_song_ids = {value for value in song_changes.values() if value}
            new_playlist_ids = {value for value in playlist_changes.values() if value}
            # Records outside this run must not keep an ID that is being
            # assigned elsewhere (for example a song added mid-reconcile).
            if new_song_ids:
                for song in db.scalars(select(Song).where(Song.navidrome_id.in_(new_song_ids))).all():
                    song.navidrome_id = None
            if new_playlist_ids:
                for playlist in db.scalars(
                    select(Playlist).where(Playlist.navidrome_playlist_id.in_(new_playlist_ids))
                ).all():
                    playlist.navidrome_playlist_id = None
            db.flush()
            for song in db.scalars(select(Song).where(Song.id.in_([k for k, v in song_changes.items() if v]))).all():
                song.navidrome_id = song_changes[song.id]
            for playlist in db.scalars(
                select(Playlist).where(Playlist.id.in_([k for k, v in playlist_changes.items() if v]))
            ).all():
                playlist.navidrome_playlist_id = playlist_changes[playlist.id]
            self._write_state(db, state)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def reconcile(self, *, trigger: str = "manual", client: NavidromeClient | None = None) -> dict[str, Any]:
        """Refresh every persisted Navidrome reference from the live catalog."""
        client = client or self.client_factory()
        if not client.configured:
            return {"state": "unconfigured", "trigger": trigger}
        if not self._lock.acquire(blocking=False):
            return {"state": "busy", "trigger": trigger}
        try:
            status = await client.status()
            if not status.get("reachable"):
                return {"state": "unavailable", "trigger": trigger, "error": status.get("error")}
            if status.get("scanning"):
                # A partial catalog would clear IDs for songs not yet indexed.
                return {"state": "scanning", "trigger": trigger}
            server_version = status.get("server_version")
            remote_songs, remote_playlists = await asyncio.gather(
                client.library_songs(), client.get_playlists()
            )
            local_songs, local_playlists = await asyncio.to_thread(self._read_local)
            song_assignments, methods = self._match_songs(local_songs, remote_songs)
            playlist_assignments = self._match_playlists(local_playlists, remote_playlists)
            song_counts, song_changes = self._summarize(local_songs, lambda s: s.navidrome_id, song_assignments)
            playlist_counts, playlist_changes = self._summarize(
                local_playlists, lambda p: p.navidrome_playlist_id, playlist_assignments
            )
            reconciled_at = utcnow_naive().isoformat() + "Z"
            result = {
                "state": "completed",
                "trigger": trigger,
                "server_version": server_version,
                "id_scheme": navidrome_id_scheme(server_version),
                "reconciled_at": reconciled_at,
                "songs": {**song_counts, "matched_by": methods},
                "playlists": playlist_counts,
                "remote": {"songs": len(remote_songs), "playlists": len(remote_playlists)},
            }
            state = {
                "server_version": server_version,
                "id_scheme": navidrome_id_scheme(server_version),
                "reconciled_at": reconciled_at,
                "trigger": trigger,
                "songs": song_counts,
                "playlists": playlist_counts,
            }
            await asyncio.to_thread(self._apply, song_changes, playlist_changes, state)
            logger.info(
                "Navidrome ID reconciliation ({}, server {}): songs checked={} updated={} "
                "unchanged={} unresolved={} skipped={} matched_by={}; playlists checked={} "
                "updated={} unchanged={} unresolved={} skipped={}.",
                trigger,
                server_version,
                song_counts["checked"],
                song_counts["updated"],
                song_counts["unchanged"],
                song_counts["unresolved"],
                song_counts["skipped"],
                methods,
                playlist_counts["checked"],
                playlist_counts["updated"],
                playlist_counts["unchanged"],
                playlist_counts["unresolved"],
                playlist_counts["skipped"],
            )
            return result
        except NavidromeError as error:
            logger.warning("Navidrome ID reconciliation did not complete: {}", error)
            return {"state": "failed", "trigger": trigger, "code": error.code, "error": str(error)}
        finally:
            self._lock.release()

    def last_result(self) -> dict[str, Any]:
        return self._read_state()


navidrome_id_reconciler = NavidromeIdReconciler()
