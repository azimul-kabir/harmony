from pathlib import Path
from typing import Iterator

from sqlalchemy.orm import Session

from app.database.crud import (
    UpsertStatus,
    delete_missing_songs,
)
from app.services.library_import import import_file

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


def scan_library(
    root: str | Path,
    db: Session,
) -> dict:
    scanned_paths: set[str] = set()

    processed = 0
    new = 0
    updated = 0
    unchanged = 0

    for file in discover_music(root):
        scanned_paths.add(str(file.resolve()))

        status = import_file(
            db=db,
            path=file,
        )

        if status is None:
            continue

        if status == UpsertStatus.NEW:
            new += 1
        elif status == UpsertStatus.UPDATED:
            updated += 1
        elif status == UpsertStatus.UNCHANGED:
            unchanged += 1
        else:
            raise ValueError(f"Unexpected upsert status: {status}")

        processed += 1

    removed = delete_missing_songs(
        db,
        scanned_paths,
    )

    return {
        "processed": processed,
        "new": new,
        "updated": updated,
        "unchanged": unchanged,
        "removed": removed,
    }