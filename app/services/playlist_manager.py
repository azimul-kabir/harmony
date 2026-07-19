import os
from pathlib import Path
from datetime import datetime, UTC
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import logger
from app.database.models import Playlist, PlaylistTrack, Song, SyncSource
from app.domain.playlist import Playlist as DomainPlaylist
from app.services.library_paths import _safe

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

    # Rebuild playlist track mapping cleanly
    db.query(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist.id).delete()
    
    for idx, track in enumerate(domain_playlist.tracks):
        if track.spotify_track_id:
            pt = PlaylistTrack(
                playlist_id=playlist.id, 
                spotify_track_id=track.spotify_track_id, 
                position=idx + 1
            )
            db.add(pt)
            
    db.commit()
    db.refresh(playlist)
    return playlist

def export_m3u(db: Session, playlist: Playlist, domain_tracks=None) -> None:
    """Generates an M3U file, tracking down existing library songs via ID or text matching."""
    settings = get_settings()
    playlist_dir = Path(settings.music_path) / "Playlists"
    playlist_dir.mkdir(parents=True, exist_ok=True)

    safe_name = playlist.name
        for char in '<>:"/\\|?*':
            safe_name = safe_name.replace(char, "_")

    file_path = playlist_dir / f"{safe_name}.m3u"

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

    try:
        with open(file_path, "w", encoding="utf-8") as f:
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
                    # Best Strategy: Strict database ID match found
                    artist = song.artist or "Unknown Artist"
                    title = song.title or "Unknown Title"
                    duration = int(song.duration) if song.duration else -1
                    full_song_path = Path(song.path)
                else:
                    # Secondary Strategy: Extract metadata from Domain object or Job
                    if dt:
                        title = dt.title
                        artist = dt.artist
                    elif job:
                        title = job.title
                        artist = job.artist

                    if title and title != "Unknown Title":
                        # Looser text-based fallback: match mainly by title to avoid issues 
                        # where ID3 tag artists differ slightly from Spotify official metadata.
                        fallback_song = db.query(Song).filter(
                            func.lower(Song.title) == title.lower()
                        ).first()
                        
                        if fallback_song:
                            artist = fallback_song.artist or artist
                            title = fallback_song.title or title
                            duration = int(fallback_song.duration) if fallback_song.duration else -1
                            full_song_path = Path(fallback_song.path)
                            
                            # Self-healing: Update the DB so we don't need text fallback next time
                            if not fallback_song.spotify_track_id:
                                fallback_song.spotify_track_id = pt.spotify_track_id
                                db.commit()
                                
                        elif job:
                            # Placeholder for paths currently queueing down the worker pipeline
                            album_artist = _safe(job.album_artist or job.artist or "Unknown Artist")
                            album = _safe(job.album) if job.album else "Singles"
                            track_num = f"{job.track:02d} - " if job.track is not None else ""
                            filename = f"{track_num}{_safe(title)}.mp3"
                            full_song_path = Path(settings.music_path) / album_artist / album / filename
                            
                        elif dt:
                            # Ultimate Fallback: The song exists but has a weird name we couldn't match,
                            # OR it was completely deleted. Predict the expected path using fresh Spotify data.
                            album_artist = _safe(dt.album_artist or dt.artist or "Unknown Artist")
                            album = _safe(dt.album) if dt.album else "Singles"
                            track_num = f"{dt.track:02d} - " if dt.track is not None else ""
                            filename = f"{track_num}{_safe(title)}.mp3"
                            full_song_path = Path(settings.music_path) / album_artist / album / filename
                            
                if not full_song_path:
                    continue  # Should almost never happen now
                
                try:
                    rel_path = os.path.relpath(full_song_path, playlist_dir)
                except ValueError:
                    rel_path = str(full_song_path)
                    
                f.write(f"#EXTINF:{duration},{artist} - {title}\n")
                f.write(f"{rel_path}\n")
                
        logger.info("Exported M3U playlist: {} with {} tracks mapped.", file_path.name, len(playlist.tracks))
    except Exception as e:
        logger.error("Failed to export M3U for {}: {}", playlist.name, e)

def export_all_m3us(db: Session) -> None:
    """Utility to regenerate all playlists"""
    for p in db.query(Playlist).all():
        export_m3u(db, p)
