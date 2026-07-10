from pathlib import Path

from sqlalchemy.orm import Session

from app.services.import_engine import import_download
from app.services.scanner import scan_library
from app.core.config import get_settings

settings = get_settings()


def import_downloaded_track(
    db: Session,
    downloaded_file: Path,
) -> Path:
    destination = import_download(
        db=db,
        downloaded_file=downloaded_file,
    )

    scan_library(
        db=db,
        library=Path(settings.music_path),
    )

    return destination