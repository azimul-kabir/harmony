"""Reusable read-model helpers for Library API and integration consumers."""

from datetime import UTC, datetime, timedelta
from typing import Any, Iterable

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, joinedload

from app.database.models import Playlist, PlaylistTrack, Song
from app.services.artwork import artwork_url, serialize_artwork
from app.core.time import utcnow_naive


RECENTLY_ADDED_DAYS = 7


def with_song_artwork(statement: Select) -> Select:
    """Eager-load the to-one artwork relation and prevent per-song SQL queries."""
    return statement.options(joinedload(Song.artwork))


def playlist_sources_for_tracks(
    db: Session,
    spotify_track_ids: Iterable[str | None],
) -> dict[str, list[dict[str, Any]]]:
    """Load playlist provenance for a result page in one indexed query."""
    identifiers = {identifier for identifier in spotify_track_ids if identifier}
    if not identifiers:
        return {}
    rows = db.execute(
        select(
            PlaylistTrack.spotify_track_id,
            Playlist.id,
            Playlist.name,
            Playlist.spotify_id,
        )
        .join(Playlist, Playlist.id == PlaylistTrack.playlist_id)
        .where(PlaylistTrack.spotify_track_id.in_(identifiers))
        .order_by(Playlist.name)
    )
    sources: dict[str, list[dict[str, Any]]] = {}
    for spotify_track_id, playlist_id, name, spotify_id in rows:
        sources.setdefault(spotify_track_id, []).append(
            {"id": playlist_id, "name": name, "spotify_id": spotify_id}
        )
    return sources


def serialize_song(
    song: Song,
    playlist_sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the stable Library Song read model used by APIs and integrations."""
    cutoff = utcnow_naive() - timedelta(days=RECENTLY_ADDED_DAYS)
    date_added = (
        song.created_at
        or song.last_indexed_at
        or song.last_modified
        or (
            datetime.fromtimestamp(song.modified_time, tz=UTC).replace(tzinfo=None)
            if song.modified_time is not None
            else utcnow_naive()
        )
    )
    return {
        "id": song.id,
        "path": song.path,
        "filename": song.filename,
        "artist": song.artist,
        "album": song.album,
        "album_artist": song.album_artist,
        "title": song.title,
        "track_number": song.track,
        "disc_number": song.disc,
        "track": song.track,
        "disc": song.disc,
        "genre": song.genre,
        "year": song.year,
        "duration": song.duration,
        "bitrate": song.bitrate,
        "codec": song.codec,
        "sample_rate": song.sample_rate,
        "file_size": song.file_size,
        "artwork_status": song.artwork_status,
        "artwork_id": song.artwork_id,
        "artwork": serialize_artwork(song.artwork) if song.artwork else None,
        "cover_url": artwork_url(song.artwork_id) or song.cover_url,
        "date_added": date_added,
        "recently_added": date_added >= cutoff,
        "last_modified": song.last_modified,
        "last_indexed_at": song.last_indexed_at,
        "availability_status": song.availability_status,
        "spotify_track_id": song.spotify_track_id,
        "musicbrainz_recording_id": song.musicbrainz_recording_id,
        "isrc": song.isrc,
        "download_source": song.download_source,
        "playlist_sources": playlist_sources or [],
    }


def serialize_song_page(db: Session, songs: Iterable[Song]) -> list[dict[str, Any]]:
    """Serialize an already-bounded result page with batched playlist provenance."""
    items = list(songs)
    source_map = playlist_sources_for_tracks(db, (song.spotify_track_id for song in items))
    return [
        serialize_song(song, source_map.get(song.spotify_track_id or "", []))
        for song in items
    ]
