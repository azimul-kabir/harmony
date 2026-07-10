from pathlib import Path
from sqlalchemy import func

from fastapi import APIRouter
from sqlalchemy import select

from app.database.models import Song
from app.database.session import SessionLocal
from app.services.scanner import scan_library
from app.core.config import get_settings

settings = get_settings()

router = APIRouter(
    prefix="/api/library",
    tags=["library"],
)


@router.get("")
def list_library():
    db = SessionLocal()

    try:
        songs = (
            db.execute(
                select(Song).order_by(
                    Song.album_artist,
                    Song.album,
                    Song.disc,
                    Song.track,
                    Song.title,
                )
            )
            .scalars()
            .all()
        )

        return [
            {
                "id": song.id,
                "title": song.title,
                "artist": song.artist,
                "album_artist": song.album_artist,
                "album": song.album,
                "track": song.track,
                "disc": song.disc,
                "year": song.year,
                "genre": song.genre,
                "path": song.path,
            }
            for song in songs
        ]

    finally:
        db.close()


@router.post("/scan")
def scan_music_library():
    db = SessionLocal()

    try:
        scan_library(
            db=db,
            library=Path(settings.music_path),
        )

        count = db.scalar(select(func.count()).select_from(Song))

        return {
            "status": "completed",
            "tracks": count,
        }

    finally:
        db.close()
