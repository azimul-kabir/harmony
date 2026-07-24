from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.time import utcnow_naive
from app.database.models import Playlist, Song
from app.database.session import SessionLocal
from app.services.navidrome import NavidromeClient, NavidromeError


class NavidromeDirectSyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class DirectSyncResult:
    playlist_id: int
    navidrome_playlist_id: str
    track_count: int


def _normalized(value: Any) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(character for character in decomposed if character.isalnum())


def _duration(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _candidate_score(
    song: Song,
    candidate: dict[str, Any],
    *,
    duration_tolerance: float,
) -> int | None:
    title = _normalized(song.title)
    if not title or title != _normalized(candidate.get("title")):
        return None

    score = 40
    artist = _normalized(song.artist or song.album_artist)
    candidate_artist = _normalized(
        candidate.get("artist") or candidate.get("albumArtist")
    )
    if artist and candidate_artist:
        if artist == candidate_artist:
            score += 30
        elif artist in candidate_artist or candidate_artist in artist:
            score += 20

    album = _normalized(song.album)
    if album and album == _normalized(candidate.get("album")):
        score += 15

    song_duration = _duration(song.duration)
    candidate_duration = _duration(candidate.get("duration"))
    if song_duration is not None and candidate_duration is not None:
        difference = abs(song_duration - candidate_duration)
        if difference <= 2:
            score += 15
        elif difference <= duration_tolerance:
            score += 8

    candidate_path = candidate.get("path")
    if candidate_path and _normalized(Path(song.path).name) == _normalized(
        Path(str(candidate_path)).name
    ):
        score += 25
    return score


def select_song_match(
    song: Song,
    candidates: list[dict[str, Any]],
    *,
    duration_tolerance: float = 5.0,
) -> dict[str, Any] | None:
    scored = [
        (score, candidate)
        for candidate in candidates
        if (score := _candidate_score(
            song,
            candidate,
            duration_tolerance=duration_tolerance,
        ))
        is not None
        and score >= 70
        and candidate.get("id")
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        return None
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


class NavidromeDirectPlaylistSync:
    def __init__(
        self,
        *,
        settings=None,
        client: NavidromeClient | None = None,
        session_factory=SessionLocal,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client or NavidromeClient(self.settings)
        self.session_factory = session_factory

    async def _resolve_song(self, song: Song) -> str:
        if song.navidrome_id:
            try:
                candidate = await self.client.get_song(song.navidrome_id)
                if select_song_match(
                    song,
                    [candidate],
                    duration_tolerance=self.settings.navidrome_direct_duration_tolerance_seconds,
                ):
                    return song.navidrome_id
            except NavidromeError:
                pass
            song.navidrome_id = None

        query = " ".join(
            value for value in (song.title, song.artist) if value
        ).strip()
        candidates = await self.client.search_songs(
            query,
            count=self.settings.navidrome_direct_search_limit,
        )
        match = select_song_match(
            song,
            candidates,
            duration_tolerance=self.settings.navidrome_direct_duration_tolerance_seconds,
        )
        if not match:
            raise NavidromeDirectSyncError(
                f'Could not uniquely match "{song.artist or "Unknown"} - '
                f'{song.title or Path(song.path).name}" in Navidrome.'
            )
        song.navidrome_id = str(match["id"])
        return song.navidrome_id

    async def _target_playlist(
        self, playlist: Playlist
    ) -> dict[str, Any] | None:
        if playlist.navidrome_playlist_id:
            try:
                return await self.client.get_playlist(
                    playlist.navidrome_playlist_id
                )
            except NavidromeError:
                playlist.navidrome_playlist_id = None

        matches = [
            item
            for item in await self.client.get_playlists()
            if str(item.get("name") or "").casefold()
            == playlist.name.casefold()
        ]
        if len(matches) > 1:
            raise NavidromeDirectSyncError(
                f'More than one Navidrome playlist is named "{playlist.name}".'
            )
        return matches[0] if matches else None

    @staticmethod
    def _entry_ids(playlist: dict[str, Any]) -> list[str]:
        entries = playlist.get("entry") or []
        if isinstance(entries, dict):
            entries = [entries]
        return [
            str(entry["id"])
            for entry in entries
            if isinstance(entry, dict) and entry.get("id")
        ]

    async def reconcile(self, playlist_id: int) -> DirectSyncResult:
        db = self.session_factory()
        try:
            playlist = db.scalar(
                select(Playlist)
                .options(selectinload(Playlist.tracks))
                .where(Playlist.id == playlist_id)
            )
            if not playlist:
                raise NavidromeDirectSyncError(
                    f"Playlist #{playlist_id} no longer exists."
                )

            spotify_ids = [
                track.spotify_track_id for track in playlist.tracks
            ]
            songs = db.scalars(
                select(Song).where(Song.spotify_track_id.in_(spotify_ids))
            ).all()
            songs_by_spotify_id = {
                song.spotify_track_id: song for song in songs
            }
            ordered_songs = [
                songs_by_spotify_id[spotify_id]
                for spotify_id in spotify_ids
                if spotify_id in songs_by_spotify_id
                and Path(songs_by_spotify_id[spotify_id].path).is_file()
            ]
            if not ordered_songs:
                raise NavidromeDirectSyncError(
                    f'Playlist "{playlist.name}" has no indexed local tracks.'
                )

            navidrome_song_ids = [
                await self._resolve_song(song) for song in ordered_songs
            ]
            target = await self._target_playlist(playlist)
            if target and target.get("readonly") is True:
                raise NavidromeDirectSyncError(
                    f'Navidrome playlist "{playlist.name}" is read-only.'
                )
            target_id = str(target["id"]) if target and target.get("id") else None
            replaced = await self.client.replace_playlist(
                name=playlist.name,
                song_ids=navidrome_song_ids,
                playlist_id=target_id,
            )
            navidrome_playlist_id = str(replaced.get("id") or target_id or "")
            if not navidrome_playlist_id:
                raise NavidromeDirectSyncError(
                    "Navidrome did not return the playlist ID."
                )
            verified = await self.client.get_playlist(navidrome_playlist_id)
            if self._entry_ids(verified) != navidrome_song_ids:
                raise NavidromeDirectSyncError(
                    "Navidrome returned a different playlist track order."
                )

            playlist.navidrome_playlist_id = navidrome_playlist_id
            playlist.navidrome_sync_status = "synced"
            playlist.navidrome_synced_track_count = len(navidrome_song_ids)
            playlist.navidrome_sync_error = None
            playlist.navidrome_synced_at = utcnow_naive()
            db.commit()
            return DirectSyncResult(
                playlist_id=playlist.id,
                navidrome_playlist_id=navidrome_playlist_id,
                track_count=len(navidrome_song_ids),
            )
        except Exception as error:
            db.rollback()
            playlist = db.get(Playlist, playlist_id)
            if playlist:
                playlist.navidrome_sync_status = "fallback"
                playlist.navidrome_sync_error = str(error)[:2000]
                db.commit()
            raise
        finally:
            db.close()
