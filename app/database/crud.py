from enum import Enum

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.models import Song, SongSourceIdentity


class UpsertStatus(str, Enum):
    NEW = "new"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


def find_song(
    db: Session,
    *,
    title: str | None = None,
    artist: str | None = None,
    album: str | None = None,
    spotify_track_id: str | None = None,
    isrc: str | None = None,
) -> Song | None:
    if spotify_track_id:
        song = db.scalar(
            select(Song).where(Song.spotify_track_id == spotify_track_id)
        )

        if song is not None:
            return song
        alias = db.get(SongSourceIdentity, ("spotify", spotify_track_id))
        if alias is not None:
            return alias.song

    if isrc:
        song = db.scalar(select(Song).where(Song.isrc == isrc))

        if song is not None:
            return song

    if not title or not artist:
        return None

    return db.scalar(
        select(Song).where(
            func.lower(Song.title) == title.lower(),
            func.lower(Song.artist) == artist.lower(),
        )
    )


def find_song_by_source(
    db: Session,
    provider: str,
    item_id: str | None,
) -> Song | None:
    if not item_id:
        return None
    alias = db.get(SongSourceIdentity, (provider or "spotify", item_id))
    return alias.song if alias is not None else None


def link_song_source(
    db: Session,
    song: Song,
    provider: str,
    item_id: str | None,
) -> None:
    """Remember that a provider item resolves to an indexed library file."""
    if not item_id:
        return
    key = (provider or "spotify", item_id)
    alias = db.get(SongSourceIdentity, key)
    if alias is None:
        db.add(
            SongSourceIdentity(
                provider=key[0],
                item_id=key[1],
                song_id=song.id,
            )
        )
    else:
        alias.song_id = song.id


def library_statistics(db: Session) -> dict:
    songs = db.scalar(select(func.count()).select_from(Song)) or 0

    albums = db.scalar(select(func.count(func.distinct(Song.album)))) or 0

    artists = db.scalar(select(func.count(func.distinct(Song.artist)))) or 0

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
    song = db.scalar(select(Song).where(Song.path == metadata["path"]))

    if song is None:
        song = Song(**metadata)
        # A watcher event and an API request can race on a newly discovered
        # file. ``songs.path`` is the authoritative uniqueness boundary, but
        # a select-then-insert alone is not atomic.
        try:
            with db.begin_nested():
                db.add(song)
                db.flush()
        except IntegrityError:
            song = db.scalar(select(Song).where(Song.path == metadata["path"]))
            if song is None:  # pragma: no cover - protects unusual DB drivers
                raise
            changed = False
            for key, value in metadata.items():
                if getattr(song, key) != value:
                    setattr(song, key, value)
                    changed = True
            if commit:
                db.commit()
                db.refresh(song)
            return (UpsertStatus.UPDATED if changed else UpsertStatus.UNCHANGED), song

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
        db.scalars(select(Song).where(Song.path.not_in(existing_paths)))
    )

    count = len(songs_to_delete)

    for song in songs_to_delete:
        db.delete(song)

    db.commit()

    return count
