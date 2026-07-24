from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from pydantic import BaseModel

from app.api.schemas.comparison import PlaylistComparisonResponse
from app.api.schemas.playlist import PlaylistImportRequest
from app.api.schemas.playlist_response import PlaylistResponse
from app.database.session import get_db
from app.database.models import Playlist, Song
from app.services.comparison import compare_with_library
from app.services.playlist import import_playlist
from app.services.playlist_download import download_playlist
from app.services.playlist_manager import playlist_file_path

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


@router.delete("/{playlist_id}")
def delete_playlist(playlist_id: int, db: Session = Depends(get_db)):
    playlist = db.get(Playlist, playlist_id)
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    same_name_exists = db.scalar(
        select(Playlist.id).where(
            Playlist.name == playlist.name,
            Playlist.id != playlist.id,
        )
    )
    if same_name_exists is None:
        file_path = playlist_file_path(playlist.name)
        try:
            file_path.unlink(missing_ok=True)
        except OSError as error:
            raise HTTPException(
                status_code=409,
                detail="Harmony could not remove the playlist M3U.",
            ) from error

    name = playlist.name
    db.delete(playlist)
    db.commit()
    return {
        "id": playlist_id,
        "name": name,
        "message": "Playlist deleted. Library songs were not removed.",
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
        
    file_path = playlist_file_path(playlist.name)
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="M3U file not found on disk")
        
    return FileResponse(
        path=file_path, 
        filename=file_path.name,
        media_type="application/vnd.apple.mpegurl"
    )
