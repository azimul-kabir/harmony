from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import Artwork, Song
from app.database.session import get_db
from app.services.artwork import (
    MAX_EMBEDDED_ARTWORK_BYTES,
    ArtworkService,
    ArtworkValidationError,
    serialize_artwork,
)
from app.services.library_events import library_events


router = APIRouter(prefix="/api/artwork", tags=["artwork"])


@router.get("")
def list_artwork(
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    items = db.scalars(
        select(Artwork).order_by(Artwork.created_at.desc()).offset(offset).limit(limit)
    ).all()
    total = db.scalar(select(func.count()).select_from(Artwork)) or 0
    return {
        "items": [serialize_artwork(item) for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{artwork_id}")
def get_artwork(artwork_id: int, db: Session = Depends(get_db)):
    artwork = db.get(Artwork, artwork_id)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")
    return serialize_artwork(artwork)


@router.get("/{artwork_id}/file")
def get_artwork_file(artwork_id: int, db: Session = Depends(get_db)):
    artwork = db.get(Artwork, artwork_id)
    if artwork is None:
        raise HTTPException(status_code=404, detail="Artwork not found")
    path = Path(artwork.cache_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Cached artwork file is missing")
    return FileResponse(
        path,
        media_type=artwork.mime_type,
        filename=path.name,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.post("/songs/{song_id}", summary="Upload and associate manual Song artwork")
async def upload_song_artwork(
    song_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    song = db.get(Song, song_id)
    if song is None:
        raise HTTPException(status_code=404, detail="Song not found")
    data = await file.read(MAX_EMBEDDED_ARTWORK_BYTES + 1)
    await file.close()
    service = ArtworkService()
    try:
        artwork = service.cache_manual_upload(db, data)
    except ArtworkValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    previous_id = song.artwork_id
    service.associate(song, artwork)
    db.commit()
    db.refresh(artwork)
    library_events.publish("library.track.updated", path=song.path, song_id=song.id)
    return {
        "song_id": song.id,
        "previous_artwork_id": previous_id,
        "artwork": serialize_artwork(artwork),
        "message": "Canonical artwork updated. Audio-file artwork was not modified.",
    }


@router.delete("/songs/{song_id}", summary="Remove a Song artwork association")
def remove_song_artwork(song_id: int, db: Session = Depends(get_db)):
    song = db.get(Song, song_id)
    if song is None:
        raise HTTPException(status_code=404, detail="Song not found")
    previous_id = song.artwork_id
    ArtworkService().associate(song, None)
    db.commit()
    library_events.publish("library.track.updated", path=song.path, song_id=song.id)
    return {
        "song_id": song.id,
        "previous_artwork_id": previous_id,
        "artwork": None,
        "message": "Canonical artwork association removed. Cached files and audio-file artwork were not modified.",
    }
