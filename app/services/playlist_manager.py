import os
from pathlib import Path
from datetime import datetime, UTC
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database.models import Playlist, PlaylistTrack, Song, SyncSource
from app.domain.playlist import Playlist as DomainPlaylist
from app.core.config import get_settings
from app.core.logging import logger

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
    
    # Store snapshot ID if your Spotify client supports fetching it
    if hasattr(domain_playlist, 'snapshot_id'):
        playlist.spotify_snapshot_id = domain_playlist.snapshot_id

    db.commit()
    db.refresh(playlist)

    # Rebuild playlist track mapping
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

def export_m3u(db: Session, playlist: Playlist) -> None:
    """Generates an M3U file using relative paths for Navidrome."""
    settings = get_settings()
    playlist_dir = Path(settings.music_path) / "Playlists"
    playlist_dir.mkdir(parents=True, exist_ok=True)
    
    # Clean filename
    safe_name = "".join([c if c.isalnum() or c in " -_" else "_" for c in playlist.name])
    file_path = playlist_dir / f"{safe_name}.m3u"
    
    # Fetch all locally downloaded songs that belong in this playlist
    track_ids = [pt.spotify_track_id for pt in playlist.tracks]
    songs = db.query(Song).filter(Song.spotify_track_id.in_(track_ids)).all()
    song_map = {s.spotify_track_id: s for s in songs}
    
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for pt in playlist.tracks:
                song = song_map.get(pt.spotify_track_id)
                # If song isn't downloaded yet, skip it for now. 
                # It will be included automatically on the next export cycle.
                if not song:
                    continue 
                
                song_path = Path(song.path)
                try:
                    rel_path = os.path.relpath(song_path, playlist_dir)
                except ValueError:
                    rel_path = str(song_path)
                    
                duration = int(song.duration) if song.duration else -1
                artist = song.artist or "Unknown Artist"
                title = song.title or "Unknown Title"
                
                f.write(f"#EXTINF:{duration},{artist} - {title}\n")
                f.write(f"{rel_path}\n")
                
        logger.info("Exported M3U playlist: {}", file_path.name)
    except Exception as e:
        logger.error("Failed to export M3U for {}: {}", playlist.name, e)

def export_all_m3us(db: Session) -> None:
    """Utility to regenerate all playlists (Triggered after a download finishes)"""
    for p in db.query(Playlist).all():
        export_m3u(db, p)
