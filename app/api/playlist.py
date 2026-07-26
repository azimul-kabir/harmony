import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from pydantic import BaseModel

from app.api.schemas.comparison import PlaylistComparisonResponse
from app.api.schemas.playlist import PlaylistImportRequest
from app.api.schemas.playlist_response import PlaylistResponse
from app.database.session import get_db
from app.database.models import DownloadJob, Playlist, Song
from app.services.artwork import artwork_url
from app.services.comparison import compare_with_library
from app.services.playlist import import_playlist
from app.services.playlist_download import download_playlist
from app.services.playlist_manager import (
    PLAYLIST_ARTWORK_SUFFIXES,
    playlist_artwork_path,
    playlist_file_path,
    remove_playlist_artwork,
)
from app.services import auto_playlists

router = APIRouter(
    prefix="/api/playlists",
    tags=["Playlists"],
)

class PlaylistDownloadRequest(BaseModel):
    url: str


class AutoPlaylistRequest(BaseModel):
    limit: int = 50
    enabled: bool = True


PLAYLIST_ARTWORK_MAX_BYTES = 10 * 1024 * 1024
PLAYLIST_ARTWORK_TYPES = {
    "image/jpeg": (".jpg", (b"\xff\xd8\xff",)),
    "image/png": (".png", (b"\x89PNG\r\n\x1a\n",)),
    "image/webp": (".webp", (b"RIFF",)),
    "image/gif": (".gif", (b"GIF87a", b"GIF89a")),
}


def _playlist_artwork_type(content_type: str | None, content: bytes) -> tuple[str, str]:
    normalized_type = (content_type or "").lower().split(";", 1)[0]
    configured = PLAYLIST_ARTWORK_TYPES.get(normalized_type)
    if configured is None:
        raise HTTPException(
            status_code=415,
            detail="Playlist artwork must be JPEG, PNG, WebP, or GIF.",
        )
    suffix, signatures = configured
    valid = any(content.startswith(signature) for signature in signatures)
    if normalized_type == "image/webp":
        valid = valid and len(content) >= 12 and content[8:12] == b"WEBP"
    if not valid:
        raise HTTPException(status_code=415, detail="The uploaded image is invalid.")
    return normalized_type, suffix


@router.get("/auto/definitions")
def auto_playlist_definitions(db: Session = Depends(get_db)):
    return auto_playlists.definitions(db)


@router.post("/auto/{rule_id}/generate")
def generate_auto_playlist(
    rule_id: str,
    request: AutoPlaylistRequest,
    db: Session = Depends(get_db),
):
    try:
        return auto_playlists.generate(
            db,
            rule_id,
            limit=request.limit,
            enabled=request.enabled,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Auto-playlist definition not found.") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


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
    jobs = db.scalars(
        select(DownloadJob)
        .where(DownloadJob.spotify_track_id.in_(spotify_ids))
        .order_by(DownloadJob.id.desc())
    ).all()
    jobs_by_spotify_id = {}
    for job in jobs:
        jobs_by_spotify_id.setdefault(job.spotify_track_id, job)

    tracks = []
    for track in playlist.tracks:
        song = songs_by_spotify_id.get(track.spotify_track_id)
        job = jobs_by_spotify_id.get(track.spotify_track_id)
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
                "cover_url": (
                    (artwork_url(song.artwork_id) or song.cover_url)
                    if song
                    else (job.cover_url if job else None)
                ),
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


@router.get("/{playlist_id}/artwork")
def playlist_artwork(playlist_id: int, db: Session = Depends(get_db)):
    playlist = db.get(Playlist, playlist_id)
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")
    file_path = playlist_artwork_path(playlist.name)
    if file_path is None:
        raise HTTPException(status_code=404, detail="Playlist artwork not found")
    media_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }[file_path.suffix.lower()]
    return FileResponse(file_path, media_type=media_type)


@router.post("/{playlist_id}/artwork")
async def replace_playlist_artwork(
    playlist_id: int,
    artwork: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    playlist = db.get(Playlist, playlist_id)
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    content = await artwork.read(PLAYLIST_ARTWORK_MAX_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="Choose an image to upload.")
    if len(content) > PLAYLIST_ARTWORK_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Playlist artwork cannot exceed 10 MB.")
    media_type, suffix = _playlist_artwork_type(artwork.content_type, content)

    target = playlist_file_path(playlist.name).with_suffix(suffix)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=target.parent,
            prefix=f".{target.stem}.",
            suffix=f"{suffix}.tmp",
            delete=False,
        ) as file:
            temporary_path = Path(file.name)
            file.write(content)
        os.replace(temporary_path, target)
        temporary_path = None
        base_path = playlist_file_path(playlist.name).with_suffix("")
        for old_suffix in PLAYLIST_ARTWORK_SUFFIXES:
            old_path = base_path.with_suffix(old_suffix)
            if old_path != target:
                old_path.unlink(missing_ok=True)
    except OSError as error:
        raise HTTPException(
            status_code=409,
            detail="Harmony could not write the playlist artwork sidecar.",
        ) from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return {
        "id": playlist.id,
        "filename": target.name,
        "media_type": media_type,
        "artwork_url": f"/api/playlists/{playlist.id}/artwork",
        "message": "Playlist artwork replaced. Scan Navidrome to display it.",
    }


@router.delete("/{playlist_id}/artwork")
def delete_playlist_artwork(playlist_id: int, db: Session = Depends(get_db)):
    playlist = db.get(Playlist, playlist_id)
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")
    try:
        remove_playlist_artwork(playlist.name)
    except OSError as error:
        raise HTTPException(
            status_code=409,
            detail="Harmony could not remove the playlist artwork.",
        ) from error
    return {
        "id": playlist.id,
        "message": "Playlist artwork removed. Navidrome will generate a tiled cover.",
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
            remove_playlist_artwork(playlist.name)
        except OSError as error:
            raise HTTPException(
                status_code=409,
                detail="Harmony could not remove the playlist files.",
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
