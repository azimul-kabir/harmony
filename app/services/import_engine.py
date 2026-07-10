from pathlib import Path

from sqlalchemy.orm import Session

from app.core.logging import logger
from app.database.crud import upsert_song
from app.services.duplicate_detector import is_duplicate
from app.services.library_paths import build_destination
from app.services.metadata import read_metadata
from app.exceptions.library import MetadataReadError
from app.exceptions.library import DuplicateTrackError
from app.exceptions.library import ImportError
import shutil


def import_download(
    db: Session,
    downloaded_file: str | Path,
) -> Path:
    """
    Import a downloaded file into the Harmony library.

    Steps:
        1. Read metadata
        2. Build destination path
        3. Check for duplicates
        4. Move file into library
        5. Update database
    """

    downloaded_file = Path(downloaded_file)

    logger.info(
        "Importing downloaded file: {}",
        downloaded_file,
    )

    metadata = read_metadata(downloaded_file)

    if metadata is None:
        raise MetadataReadError(
            f"Unable to read metadata from {downloaded_file}"
        )

    destination = build_destination(metadata)

    logger.info(
        "Destination: {}",
        destination,
    )

    if is_duplicate(destination):
        raise DuplicateTrackError(
            f"{destination} already exists."
        )

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        logger.info("Moving file...")

        shutil.move(
            str(downloaded_file),
            str(destination),
        )

        metadata["path"] = str(destination)
        metadata["filename"] = destination.name

        logger.info("Updating library database...")

        upsert_song(
            db=db,
            metadata=metadata,
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

            if destination.exists() and not downloaded_file.exists():
                try:
                    destination.rename(downloaded_file)

                except Exception:
                    logger.exception(
                        "Failed to restore downloaded file."
                    )

            raise ImportError(str(ex)) from ex