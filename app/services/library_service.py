from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.scanner import scan_library

settings = get_settings()


def rescan_library(
    db: Session,
) -> None:
    scan_library(
        db=db,
        library=Path(settings.music_path),
    )