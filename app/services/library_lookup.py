from sqlalchemy import select

from app.database.models import Song
from app.domain.track import Track


def exists(
    db,
    track: Track,
) -> Song | None:
    return db.scalar(
        select(Song).where(
            Song.title == track.title,
            Song.artist == track.artist,
            Song.album == track.album,
        )
    )