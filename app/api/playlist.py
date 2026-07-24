from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from pathlib import Path
from pydantic import BaseModel

from app.api.schemas.comparison import PlaylistComparisonResponse
from app.api.schemas.playlist import PlaylistImportRequest
from app.api.schemas.playlist_response import PlaylistResponse
from app.database.session import get_db
from app.database.models import Playlist, Song
from app.services.comparison import compare_with_library
from app.services.playlist import import_playlist
from app.services.playlist_download import download_playlist
from app.core.config import get_settings

settings = get_settings()

router = APIRouter(
    prefix="/api/playlists",
    tags=["Playlists"],
)

class PlaylistDownloadRequest(BaseModel):
    url: str


@router.get("/{playlist_id}/tracks")
def playlist_tracks(playlist_id: int, db: Session = Depends(get_db)):
    playlist = db.scalar(
        select(Playlist)
        .options(selectinload(Playlist.tracks))
        .where(Playlist.id == playlist_id)
    )
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    spotify_ids = [track.spotify_track_id for track in playlist.tracks]
    songs = db.scalars(
        select(Song).where(Song.spotify_track_id.in_(spotify_ids))
    ).all()
    songs_by_spotify_id = {
        song.spotify_track_id: song for song in songs
    }
    tracks = []
    for track in playlist.tracks:
        song = songs_by_spotify_id.get(track.spotify_track_id)
        tracks.append(
            {
                "position": track.position + 1,
                "spotify_track_id": track.spotify_track_id,
                "title": (song.title if song else None)
                or track.title
                or "Unknown title",
                "artist": (song.artist if song else None)
                or track.artist
                or "Unknown artist",
                "album": (song.album if song else None) or track.album,
                "song_id": song.id if song else None,
                "availability": (
                    song.availability_status if song else "not_in_library"
                ),
                "selectable": bool(
                    song and song.availability_status != "missing"
                ),
            }
        )
    return {
        "id": playlist.id,
        "name": playlist.name,
        "track_count": len(tracks),
        "deletable_count": sum(track["selectable"] for track in tracks),
        "tracks": tracks,
    }

@router.post("/import", response_model=PlaylistResponse)
def import_spotify_playlist(request: PlaylistImportRequest):
    playlist = import_playlist(request.url)
    return PlaylistResponse.model_validate(playlist)

@router.post("/compare", response_model=PlaylistComparisonResponse)
def compare_spotify_playlist(
    request: PlaylistImportRequest,
    db: Session = Depends(get_db),
):
    playlist = import_playlist(request.url)
    comparison = compare_with_library(db, playlist)
    return PlaylistComparisonResponse.model_validate(comparison)

@router.post("/download")
def download(
    request: PlaylistDownloadRequest,
    db: Session = Depends(get_db),
):
    return download_playlist(
        db=db,
        url=request.url,
    )

@router.get("/{playlist_id}/download")
def download_m3u(playlist_id: int, db: Session = Depends(get_db)):
    playlist = db.get(Playlist, playlist_id)
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")
        
    # Generate the expected path (matching your unicode-safe export logic)
    playlist_dir = Path(settings.music_path) / "Playlists"
    safe_name = playlist.name
    for char in '<>:"/\\|?*':
        safe_name = safe_name.replace(char, "_")
    file_path = playlist_dir / f"{safe_name}.m3u"
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="M3U file not found on disk")
        
    return FileResponse(
        path=file_path, 
        filename=f"{safe_name}.m3u", 
        media_type="application/vnd.apple.mpegurl"
    )
