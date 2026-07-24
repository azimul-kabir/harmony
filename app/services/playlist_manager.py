import os
import tempfile
from pathlib import Path
from datetime import datetime, UTC
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import logger
from app.database.models import Playlist, PlaylistTrack, Song, SyncSource
from app.domain.playlist import Playlist as DomainPlaylist
from app.services.library_paths import _safe
from app.services.library_search import library_search


def playlist_file_path(name: str) -> Path:
    settings = get_settings()
    safe_name = name
    for char in '<>:"/\\|?*':
        safe_name = safe_name.replace(char, "_")
    return Path(settings.music_path) / "Playlists" / f"{safe_name}.m3u"


def count_m3u_entries(file_path: Path) -> int:
    try:
        return sum(
            1
            for line in file_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    except (OSError, UnicodeError):
        return 0


def sync_database_playlist(db: Session, source: SyncSource, domain_playlist: DomainPlaylist) -> Playlist:
    """Updates the database with the latest Spotify playlist structure."""
    playlist = db.scalar(select(Playlist).where(Playlist.spotify_id == source.spotify_id))
    
    if not playlist:
        playlist = Playlist(spotify_id=source.spotify_id)
        db.add(playlist)
    
    playlist.name = domain_playlist.name
    playlist.track_count = len(domain_playlist.tracks)
    playlist.last_synced_at = datetime.now(UTC)
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
        if track.spotify_track_id:
            current_track_ids.add(track.spotify_track_id)
            pt = PlaylistTrack(
                playlist_id=playlist.id,
                spotify_track_id=track.spotify_track_id,
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

def export_m3u(db: Session, playlist: Playlist, domain_tracks=None) -> int:
    """Generates an M3U file, tracking down existing library songs via ID or text matching."""
    settings = get_settings()
    file_path = playlist_file_path(playlist.name)
    playlist_dir = file_path.parent
    playlist_dir.mkdir(parents=True, exist_ok=True)
    safe_name = file_path.stem
    
    # 1. Map current local downloads via strict ID lookup
    track_ids = [pt.spotify_track_id for pt in playlist.tracks]
    songs = db.query(Song).filter(Song.spotify_track_id.in_(track_ids)).all()
    song_id_map = {s.spotify_track_id: s for s in songs}
    
    # 2. Map downloading/queued jobs
    from app.database.models import DownloadJob
    jobs = db.query(DownloadJob).filter(DownloadJob.spotify_track_id.in_(track_ids)).all()
    job_map = {j.spotify_track_id: j for j in jobs}
    
    # 3. Map freshly scraped domain metadata if provided
    domain_map = {t.spotify_track_id: t for t in domain_tracks} if domain_tracks else {}
    
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
    playlists = db.scalars(
        select(Playlist)
        .join(PlaylistTrack)
        .where(PlaylistTrack.spotify_track_id == spotify_track_id)
    ).unique().all()
    for playlist in playlists:
        export_m3u(db, playlist)
    return len(playlists)

def export_all_m3us(db: Session) -> None:
    """Utility to regenerate all playlists"""
    for p in db.query(Playlist).all():
        export_m3u(db, p)
