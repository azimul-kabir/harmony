from app.domain.track import Track
import os
import tempfile
from pathlib import Path
from datetime import datetime, UTC
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import logger
from app.database.models import Playlist, PlaylistTrack, Song, SyncSource
from app.domain.playlist import Playlist as DomainPlaylist
from app.services.library_paths import _safe
from app.services.library_search import library_search

PLAYLIST_ARTWORK_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def source_identity(provider: str, item_id: str) -> str:
    """Fit provider-neutral identities into legacy playlist identifier columns."""
    return item_id if provider == "spotify" else f"{provider}:{item_id}"


def playlist_file_path(name: str) -> Path:
    settings = get_settings()
    safe_name = name
    for char in '<>:"/\\|?*':
        safe_name = safe_name.replace(char, "_")
    return Path(settings.music_path) / "Playlists" / f"{safe_name}.m3u"


def playlist_artwork_path(name: str) -> Path | None:
    """Return the first Navidrome-compatible sidecar for a playlist."""
    base_path = playlist_file_path(name).with_suffix("")
    for suffix in PLAYLIST_ARTWORK_SUFFIXES:
        candidate = base_path.with_suffix(suffix)
        if candidate.is_file():
            return candidate
    return None


def remove_playlist_artwork(name: str) -> None:
    """Remove every supported sidecar variant for a playlist."""
    base_path = playlist_file_path(name).with_suffix("")
    for suffix in PLAYLIST_ARTWORK_SUFFIXES:
        base_path.with_suffix(suffix).unlink(missing_ok=True)


def count_m3u_entries(file_path: Path) -> int:
    try:
        return sum(
            1
            for line in file_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    except (OSError, UnicodeError):
        return 0


def save_database_playlist(
    db: Session,
    source_id: str,
    domain_playlist: DomainPlaylist,
    *,
    source_provider: str = "spotify",
    synced_at: datetime | None = None,
) -> Playlist:
    """Persist an ordered source playlist independently of sync scheduling."""
    playlist_id = source_identity(source_provider, source_id)
    playlist = db.scalar(select(Playlist).where(Playlist.spotify_id == playlist_id))
    
    if not playlist:
        playlist = Playlist(spotify_id=playlist_id)
        db.add(playlist)
    
    playlist.name = domain_playlist.name
    playlist.track_count = len(domain_playlist.tracks)
    if synced_at is not None:
        playlist.last_synced_at = synced_at
    playlist.updated_at = datetime.now(UTC)
    
    if hasattr(domain_playlist, 'snapshot_id'):
        playlist.spotify_snapshot_id = domain_playlist.snapshot_id

    db.commit()
    db.refresh(playlist)

    # Rebuild playlist track mapping cleanly and refresh only affected search rows.
    previous_track_ids = set(
        db.scalars(
            select(PlaylistTrack.spotify_track_id).where(
                PlaylistTrack.playlist_id == playlist.id
            )
        ).all()
    )
    db.query(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist.id).delete()
    current_track_ids: set[str] = set()
    for idx, track in enumerate(domain_playlist.tracks):
        track_id = track.spotify_track_id
        if source_provider != "spotify" and track.source_item_id:
            track_id = source_identity(source_provider, track.source_item_id)
        if track_id:
            current_track_ids.add(track_id)
            pt = PlaylistTrack(
                playlist_id=playlist.id,
                spotify_track_id=track_id,
                position=idx + 1,
                title=track.title,
                artist=track.artist,
                album=track.album,
                album_artist=track.album_artist,
                track_number=track.track,
                duration=track.duration,
            )
            db.add(pt)
            
    db.flush()
    library_search.index_spotify_tracks(db, previous_track_ids | current_track_ids)
    db.commit()
    db.refresh(playlist)
    return playlist



def begin_playlist_refresh(db: Session, playlist: Playlist) -> None:
    """
    Clears out the previous tracks of a playlist to prepare for a fresh import.
    This should be called before appending the first batch.
    """
    db.query(PlaylistTrack).filter(PlaylistTrack.playlist_id == playlist.id).delete()
    db.commit()


def append_playlist_batch(
    db: Session,
    playlist_id: int,
    tracks: list[Track],
    start_position: int,
    source_provider: str = "spotify",
) -> None:
    """
    Appends a batch of tracks to the playlist, honoring the starting position.
    """
    # source_identity is already defined in this file

    current_track_ids: set[str] = set()
    for idx, track in enumerate(tracks):
        track_id = track.spotify_track_id
        if source_provider != "spotify" and track.source_item_id:
            track_id = source_identity(source_provider, track.source_item_id)

        if track_id:
            current_track_ids.add(track_id)

            # Upsert using standard query to allow recovery if batches overlap or restart
            existing = db.query(PlaylistTrack).filter(
                PlaylistTrack.playlist_id == playlist_id,
                PlaylistTrack.position == start_position + idx + 1
            ).first()

            if not existing:
                pt = PlaylistTrack(
                    playlist_id=playlist_id,
                    spotify_track_id=track_id,
                    position=start_position + idx + 1,
                    title=track.title,
                    artist=track.artist,
                    album=track.album,
                    album_artist=track.album_artist,
                    track_number=track.track,
                    duration=track.duration,
                )
                db.add(pt)
            else:
                existing.position = start_position + idx + 1
                existing.title = track.title
                existing.artist = track.artist
                existing.album = track.album
                existing.album_artist = track.album_artist
                existing.track_number = track.track
                existing.duration = track.duration

    db.flush()
    db.commit()


def complete_playlist_refresh(db: Session, playlist: Playlist) -> None:
    """
    Updates the playlist's track count and timestamps after all batches are imported.
    """
    playlist.track_count = db.query(PlaylistTrack).filter(PlaylistTrack.playlist_id == playlist.id).count()
    db.commit()
    db.refresh(playlist)


def sync_database_playlist(
    db: Session,
    source: SyncSource,
    domain_playlist: DomainPlaylist,
) -> Playlist:
    """Update a saved playlist as part of an explicit source sync."""
    return save_database_playlist(
        db,
        source.spotify_id,
        domain_playlist,
        synced_at=datetime.now(UTC),
    )

def export_m3u(db: Session, playlist: Playlist, domain_tracks=None) -> int:
    """Generates an M3U file, tracking down existing library songs via ID or text matching."""
    settings = get_settings()
    file_path = playlist_file_path(playlist.name)
    playlist_dir = file_path.parent
    playlist_dir.mkdir(parents=True, exist_ok=True)
    safe_name = file_path.stem
    
    # 1. Map current local downloads via strict ID lookup
    track_ids = [
        pt.spotify_track_id
        for pt in playlist.tracks
        if not pt.spotify_track_id.startswith("library:")
    ]
    songs = db.query(Song).filter(Song.spotify_track_id.in_(track_ids)).all()
    song_id_map = {s.spotify_track_id: s for s in songs}
    local_song_ids = [
        int(pt.spotify_track_id.removeprefix("library:"))
        for pt in playlist.tracks
        if pt.spotify_track_id.startswith("library:")
        and pt.spotify_track_id.removeprefix("library:").isdigit()
    ]
    local_song_map = {
        song.id: song
        for song in db.scalars(select(Song).where(Song.id.in_(local_song_ids))).all()
    }
    
    # 2. Map downloading/queued jobs
    from app.database.models import DownloadJob
    provider_item_ids = {
        identity.split(":", 1)[1]
        for identity in track_ids
        if identity.startswith("youtube_music:")
    }
    jobs = db.query(DownloadJob).filter(
        or_(
            DownloadJob.spotify_track_id.in_(track_ids),
            (
                (DownloadJob.source_provider == "youtube_music")
                & DownloadJob.source_item_id.in_(provider_item_ids)
            ),
        )
    ).all()
    job_map = {
        (
            source_identity(job.source_provider, job.source_item_id)
            if job.source_provider != "spotify" and job.source_item_id
            else job.spotify_track_id
        ): job
        for job in jobs
    }
    
    # 3. Map freshly scraped domain metadata if provided
    domain_map = {}
    for track in domain_tracks or []:
        identity = track.spotify_track_id
        if track.source_provider != "spotify" and track.source_item_id:
            identity = source_identity(track.source_provider, track.source_item_id)
        if identity:
            domain_map[identity] = track
    
    exported_count = 0
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=playlist_dir,
            prefix=f".{safe_name}.",
            suffix=".m3u.tmp",
            delete=False,
        ) as f:
            temporary_path = Path(f.name)
            f.write("#EXTM3U\n")
            
            for pt in playlist.tracks:
                song = song_id_map.get(pt.spotify_track_id)
                if song is None and pt.spotify_track_id.startswith("library:"):
                    raw_song_id = pt.spotify_track_id.removeprefix("library:")
                    song = local_song_map.get(int(raw_song_id)) if raw_song_id.isdigit() else None
                job = job_map.get(pt.spotify_track_id)
                dt = domain_map.get(pt.spotify_track_id)
                
                duration = -1
                artist = "Unknown Artist"
                title = "Unknown Title"
                full_song_path = None
                
                if song:
                    artist = song.artist or "Unknown Artist"
                    title = song.title or "Unknown Title"
                    duration = int(song.duration) if song.duration else -1
                    full_song_path = Path(song.path)
                else:
                    if dt:
                        title = dt.title
                        artist = dt.artist
                    elif pt.title:
                        title = pt.title
                        artist = pt.artist or artist
                        duration = int(pt.duration) if pt.duration else -1
                    elif job:
                        title = job.title
                        artist = job.artist
                    
                    if title and title != "Unknown Title":
                        fallback_song = db.query(Song).filter(func.lower(Song.title) == title.lower()).first()
                        if fallback_song:
                            artist = fallback_song.artist or artist
                            title = fallback_song.title or title
                            duration = int(fallback_song.duration) if fallback_song.duration else -1
                            full_song_path = Path(fallback_song.path)
                            if not fallback_song.spotify_track_id:
                                fallback_song.spotify_track_id = pt.spotify_track_id
                                db.commit()
                        elif job or pt.title:
                            album_artist = _safe(
                                (job.album_artist if job else pt.album_artist)
                                or (job.artist if job else pt.artist)
                                or "Unknown Artist"
                            )
                            source_album = job.album if job else pt.album
                            source_track = job.track if job else pt.track_number
                            album = _safe(source_album) if source_album else "Singles"
                            track_num = f"{source_track:02d} - " if source_track is not None else ""
                            filename = f"{track_num}{_safe(title)}.mp3"
                            full_song_path = Path(settings.music_path) / album_artist / album / filename
                        elif dt:
                            album_artist = _safe(dt.album_artist or dt.artist or "Unknown Artist")
                            album = _safe(dt.album) if dt.album else "Singles"
                            track_num = f"{dt.track:02d} - " if dt.track is not None else ""
                            filename = f"{track_num}{_safe(title)}.mp3"
                            full_song_path = Path(settings.music_path) / album_artist / album / filename
                
                if not full_song_path or not full_song_path.is_file():
                    continue
                    
                try:
                    rel_path = os.path.relpath(full_song_path, playlist_dir)
                except ValueError:
                    rel_path = str(full_song_path)
                    
                f.write(f"#EXTINF:{duration},{artist} - {title}\n")
                f.write(f"{rel_path}\n")
                exported_count += 1

        os.replace(temporary_path, file_path)
        temporary_path = None
        logger.info(
            "Exported M3U playlist: {} with {} of {} tracks available.",
            file_path.name,
            exported_count,
            playlist.track_count,
        )
        return exported_count
    except Exception as e:
        logger.error("Failed to export M3U for {}: {}", playlist.name, e)
        return 0
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def export_m3us_for_track(db: Session, spotify_track_id: str | None) -> int:
    """Refresh only playlists affected by a completed download."""
    if not spotify_track_id:
        return 0
    return export_m3us_for_tracks(db, [spotify_track_id])


def export_m3us_for_source_track(
    db: Session,
    source_provider: str,
    source_item_id: str | None,
    spotify_track_id: str | None,
) -> int:
    """Refresh playlists using the stable identity for the download provider."""
    item_id = spotify_track_id
    if source_provider != "spotify" and source_item_id:
        item_id = source_identity(source_provider, source_item_id)
    return export_m3us_for_track(db, item_id)


def export_m3us_for_tracks(
    db: Session, spotify_track_ids: list[str]
) -> int:
    """Refresh each playlist affected by a set of tracks exactly once."""
    if not spotify_track_ids:
        return 0
    playlists = db.scalars(
        select(Playlist)
        .join(PlaylistTrack)
        .where(
            PlaylistTrack.spotify_track_id.in_(spotify_track_ids),
            Playlist.playlist_kind != "smart",
        )
        .order_by(Playlist.id)
    ).unique().all()
    for playlist in playlists:
        export_m3u(db, playlist)
    from app.services.auto_playlists import refresh_enabled
    return len(playlists) + refresh_enabled(db)

def export_all_m3us(db: Session) -> None:
    """Utility to regenerate all playlists"""
    for p in db.query(Playlist).where(Playlist.playlist_kind != "smart").all():
        export_m3u(db, p)
    from app.services.auto_playlists import refresh_enabled
    refresh_enabled(db)
