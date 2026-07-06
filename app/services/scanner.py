from pathlib import Path
from typing import Iterator

from sqlalchemy.orm import Session

from app.database.crud import upsert_song
from app.services.metadata import read_metadata

SUPPORTED_EXTENSIONS = {
    ".mp3",
    ".flac",
    ".m4a",
    ".aac",
    ".ogg",
    ".opus",
    ".wav",
}


def discover_music(root: str | Path) -> Iterator[Path]:
    root = Path(root)

    if not root.exists():
        return

    for file in root.rglob("*"):
        if file.is_file() and file.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield file


def scan_library(root: str | Path, db: Session):
    """
    Scan a music library and import/update every song.

    Returns:
        {
            "processed": int,
            "imported": int
        }
    """

    processed = 0

    for file in discover_music(root):
        metadata = read_metadata(file)
        upsert_song(db, metadata)
        processed += 1

    return {
        "processed": processed,
        "imported": processed,
    }