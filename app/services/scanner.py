from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import logger
from app.database.crud import upsert_song
from app.database.models import Song
from app.services.metadata import read_metadata
from app.services.tags import SUPPORTED_EXTENSIONS


def scan_library(
    db: Session,
    library: Path,
) -> None:
    logger.info("Scanning {}", library)

    existing = {song.path: song for song in db.scalars(select(Song)).all()}

    found: set[str] = set()

    for file in library.rglob("*"):
        if not file.is_file() or file.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        metadata = read_metadata(file)

        metadata["path"] = str(file)
        metadata["filename"] = file.name

        upsert_song(
            db=db,
            metadata=metadata,
            commit=False,
        )

        found.add(str(file))

    for path, song in existing.items():
        if path not in found:
            logger.info("Removing missing file {}", path)
            db.delete(song)

    db.commit()

    logger.info(
        "Library scan finished. {} tracks indexed.",
        len(found),
    )
