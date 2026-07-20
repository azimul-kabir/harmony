from sqlalchemy.orm import Session

from app.database.crud_library import (
    find_song_by_path,
    save_song,
)
from app.database.models import Song

from pathlib import Path

from mutagen import File

from app.core.config import get_settings

settings = get_settings()


AUDIO_EXTENSIONS = {
    ".mp3",
    ".flac",
    ".m4a",
    ".ogg",
    ".opus",
}


def scan_library(
    db: Session,
):
    root = Path(settings.music_path)

    for file in iter_music_files(root):
        scan_file(
            db,
            file,
        )


def scan_file(
    db: Session,
    file: Path,
    cover_url: str | None = None,  # <-- NEW: Accept the cover URL from the worker
):
    tags = read_tags(file)

    stat = file.stat()

    song = find_song_by_path(
        db,
        str(file),
    )

    if song is None:
        song = Song(
            path=str(file),
            filename=file.name,
        )

    song.title = tags.get("title")
    song.artist = tags.get("artist")
    song.album = tags.get("album")
    song.album_artist = tags.get("album_artist")
    song.genre = tags.get("genre")

    # NEW: Save the cover URL if provided
    if cover_url:
        song.cover_url = cover_url

    song.file_size = stat.st_size
    song.modified_time = int(stat.st_mtime)

    save_song(
        db,
        song,
    )


def iter_music_files(root: Path):
    for path in root.rglob("*"):
        if (
            path.is_file()
            and path.suffix.lower() in AUDIO_EXTENSIONS
        ):
            yield path


def read_tags(path: Path) -> dict:
    audio = File(path, easy=True)

    if audio is None:
        return {}

    def get(key):
        value = audio.get(key)

        if not value:
            return None

        return str(value[0])

    return {
        "title": get("title"),
        "artist": get("artist"),
        "album": get("album"),
        "album_artist": get("albumartist"),
        "genre": get("genre"),
    }
