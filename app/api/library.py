import os
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import SessionLocal, get_db
from app.database.models import Song
from app.services.library_scanner import scan_library

router = APIRouter(
    prefix="/api/library",
    tags=["library"],
)

# --- Management: Deletions ---

@router.get("/songs")
def list_songs(db: Session = Depends(get_db)):
    songs = db.query(Song).all()
    return [{"id": s.id, "title": s.title, "artist": s.artist, "album": s.album} for s in songs]

@router.delete("/song/{song_id}")
def delete_song(song_id: int, db: Session = Depends(get_db)):
    song = db.get(Song, song_id)
    if song and os.path.exists(song.path):
        try:
            os.remove(song.path)
        except OSError:
            pass
        db.delete(song)
        db.commit()
    return {"status": "success"}

# --- Maintenance: Rescanning ---

@router.post("/rescan")
def rescan():
    db = SessionLocal()
    try:
        scan_library(db)
        return {"status": "ok"}
    finally:
        db.close()
