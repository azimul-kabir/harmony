from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Playlist, PlaylistTrack, Song
from app.services.playlist_manager import export_m3u


@dataclass(frozen=True, slots=True)
class AutoPlaylistDefinition:
    id: str
    name: str
    description: str
    available: bool
    unavailable_reason: str | None = None


AUTO_PLAYLISTS = (
    AutoPlaylistDefinition("recently-added", "Recently Added", "The newest songs added to the Library Index.", True),
    AutoPlaylistDefinition("recently-downloaded", "Recently Downloaded", "The newest songs acquired through Harmony.", True),
    AutoPlaylistDefinition("new-and-unplayed", "New & Unplayed", "New library songs that have not been played.", False, "Requires Navidrome play history."),
    AutoPlaylistDefinition("favorites", "Favorites", "Songs starred in Navidrome.", False, "Requires Navidrome favorite data."),
    AutoPlaylistDefinition("rediscovery", "Rediscovery", "Older favorites that have not been played recently.", False, "Requires Navidrome play history."),
    AutoPlaylistDefinition("most-played", "Most Played", "The songs you play most often.", False, "Requires Navidrome play counts."),
)


def definitions(db: Session) -> list[dict]:
    rows = {
        playlist.smart_rule: playlist
        for playlist in db.scalars(
            select(Playlist).where(Playlist.playlist_kind == "smart")
        ).all()
    }
    return [
        {
            "id": definition.id,
            "name": definition.name,
            "description": definition.description,
            "available": definition.available,
            "unavailable_reason": definition.unavailable_reason,
            "enabled": bool(rows.get(definition.id) and rows[definition.id].smart_enabled),
            "limit": rows[definition.id].smart_limit if rows.get(definition.id) else 50,
            "playlist_id": rows[definition.id].id if rows.get(definition.id) else None,
        }
        for definition in AUTO_PLAYLISTS
    ]


def _definition(rule_id: str) -> AutoPlaylistDefinition:
    definition = next((item for item in AUTO_PLAYLISTS if item.id == rule_id), None)
    if definition is None:
        raise KeyError(rule_id)
    if not definition.available:
        raise ValueError(definition.unavailable_reason or "This auto-playlist is unavailable.")
    return definition


def _song_statement(rule_id: str, limit: int):
    statement = select(Song).where(Song.availability_status == "available")
    if rule_id == "recently-downloaded":
        statement = statement.where(Song.download_source != "filesystem")
    return statement.order_by(Song.created_at.desc(), Song.id.desc()).limit(limit)


def generate(db: Session, rule_id: str, *, limit: int = 50, enabled: bool = True) -> dict:
    definition = _definition(rule_id)
    limit = max(1, min(int(limit), 500))
    playlist = db.scalar(select(Playlist).where(Playlist.smart_rule == rule_id))
    if playlist is None:
        playlist = Playlist(
            spotify_id=f"smart:{rule_id}",
            name=definition.name,
            description=definition.description,
            playlist_kind="smart",
            smart_rule=rule_id,
        )
        db.add(playlist)
        db.flush()

    playlist.smart_enabled = enabled
    playlist.smart_limit = limit
    playlist.name = definition.name
    playlist.description = definition.description
    playlist.last_synced_at = datetime.now(UTC)
    playlist.updated_at = datetime.now(UTC)
    db.query(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist.id).delete()

    songs = db.scalars(_song_statement(rule_id, limit)).all() if enabled else []
    for position, song in enumerate(songs, start=1):
        identifier = song.spotify_track_id or f"library:{song.id}"
        db.add(
            PlaylistTrack(
                playlist_id=playlist.id,
                spotify_track_id=identifier,
                position=position,
                title=song.title,
                artist=song.artist,
                album=song.album,
                album_artist=song.album_artist,
                track_number=song.track,
                duration=song.duration,
            )
        )
    playlist.track_count = len(songs)
    db.commit()
    db.refresh(playlist)
    exported_count = export_m3u(db, playlist)
    return {
        "id": playlist.id,
        "rule_id": rule_id,
        "name": playlist.name,
        "enabled": playlist.smart_enabled,
        "limit": playlist.smart_limit,
        "track_count": playlist.track_count,
        "exported_count": exported_count,
    }


def refresh_enabled(db: Session) -> int:
    playlists = db.scalars(
        select(Playlist)
        .where(
            Playlist.playlist_kind == "smart",
            Playlist.smart_enabled.is_(True),
            Playlist.smart_rule.is_not(None),
        )
        .order_by(Playlist.id)
    ).all()
    refreshed = 0
    for playlist in playlists:
        generate(
            db,
            playlist.smart_rule,
            limit=playlist.smart_limit,
            enabled=True,
        )
        refreshed += 1
    return refreshed
