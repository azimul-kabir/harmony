from pathlib import Path

from sqlalchemy.orm import Session

from app.services.import_engine import import_download
from app.services.library_scanner import scan_file


def import_downloaded_track(
    db: Session,
    downloaded_file: Path,
) -> Path:
    destination = import_download(
        db=db,
        downloaded_file=downloaded_file,
    )

    scan_file(
        db=db,
        file=destination,
    )

    return destination