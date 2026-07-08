from enum import Enum

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.database.models import Song


class UpsertStatus(str, Enum):
    NEW = "new"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


def find_song_by_title_artist(
    db: Session,
    title: str,
    artist: str,
) -> Song | None:
    return db.scalar(
        select(Song).where(
            func.lower(Song.title) == title.lower(),
            func.lower(Song.artist) == artist.lower(),
        )
    )


def library_statistics(db: Session) -> dict:
    songs = db.scalar(
        select(func.count()).select_from(Song)
    ) or 0

    albums = db.scalar(
        select(func.count(func.distinct(Song.album)))
    ) or 0

    artists = db.scalar(
        select(func.count(func.distinct(Song.artist)))
    ) or 0

    return {
        "songs": songs,
        "albums": albums,
        "artists": artists,
    }


def upsert_song(
    db: Session,
    metadata: dict,
    *,
    commit: bool = True,
) -> tuple[UpsertStatus, Song]:
    song = db.scalar(
        select(Song).where(
            Song.path == metadata["path"]
        )
    )

    if song is None:
        song = Song(**metadata)
        db.add(song)

        if commit:
            db.commit()
            db.refresh(song)

        return UpsertStatus.NEW, song

    changed = False

    for key, value in metadata.items():
        if getattr(song, key) != value:
            setattr(song, key, value)
            changed = True

    if changed:
        if commit:
            db.commit()
            db.refresh(song)

        return UpsertStatus.UPDATED, song

    return UpsertStatus.UNCHANGED, song


def delete_missing_songs(
    db: Session,
    existing_paths: set[str],
) -> int:
    songs_to_delete = list(
        db.scalars(
            select(Song).where(
                Song.path.not_in(existing_paths)
            )
        )
    )

    count = len(songs_to_delete)

    for song in songs_to_delete:
        db.delete(song)

    db.commit()

    return count