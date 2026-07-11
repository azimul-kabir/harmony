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
    audio = File(path, easy=False)

    if audio is None:
        return {}

    tags = {}

    def get(key):
        value = audio.tags.get(key) if audio.tags else None

        if isinstance(value, list):
            return str(value[0])

        return value

    tags["title"] = get("TIT2") or get("title")
    tags["artist"] = get("TPE1") or get("artist")
    tags["album"] = get("TALB") or get("album")
    tags["album_artist"] = get("TPE2") or get("albumartist")
    tags["genre"] = get("TCON") or get("genre")

    return tags