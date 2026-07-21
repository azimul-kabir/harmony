from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import Artwork
from app.database.session import get_db
from app.services.artwork import serialize_artwork


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
