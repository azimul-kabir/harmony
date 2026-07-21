from pathlib import Path
import shutil

from sqlalchemy.orm import Session

from app.core.logging import logger
from app.exceptions.library import (
    DuplicateTrackError,
    ImportError,
    MetadataReadError,
)
from app.services.duplicate_detector import is_duplicate
from app.services.library_paths import build_destination
from app.services.library_scanner import index_file
from app.services.metadata import read_metadata


def import_download(
    db: Session,
    downloaded_file: str | Path,
    download_source: str = "filesystem",
    cover_url: str | None = None,
) -> Path:
    """
    Import a downloaded file into the Harmony library.

    Steps
    -----
    1. Read metadata
    2. Build destination path
    3. Check duplicates
    4. Move file
    5. Update database
    """

    downloaded_file = Path(downloaded_file)

    logger.info(
        "Importing downloaded file: {}",
        downloaded_file,
    )

    metadata = read_metadata(downloaded_file)

    if metadata is None:
        raise MetadataReadError(f"Unable to read metadata from {downloaded_file}")

    destination = build_destination(metadata)

    logger.info(
        "Destination: {}",
        destination,
    )

    if is_duplicate(destination):
        raise DuplicateTrackError(f"{destination} already exists.")

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    moved = False

    try:
        logger.info("Moving file...")

        shutil.move(
            str(downloaded_file),
            str(destination),
        )

        moved = True

        logger.info("Updating library database...")

        index_file(
            db,
            destination,
            force=True,
            cover_url=cover_url,
            download_source=download_source,
            commit=False,
        )

        db.commit()

        logger.info(
            "Import completed: {}",
            destination,
        )

        return destination

    except Exception as ex:
        db.rollback()

        if moved and destination.exists() and not downloaded_file.exists():
            try:
                shutil.move(
                    str(destination),
                    str(downloaded_file),
                )
            except Exception:
                logger.exception("Failed to restore downloaded file.")

        raise ImportError(str(ex)) from ex
