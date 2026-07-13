from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Song


def find_song_by_path(
    db: Session,
    path: str,
):
    return db.scalar(
        select(Song).where(
            Song.path == path,
        )
    )


def save_song(
    db: Session,
    song: Song,
):
    db.add(song)
    db.commit()