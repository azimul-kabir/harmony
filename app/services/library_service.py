from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.library_scanner import IndexResult, ScanResult, index_file, scan_library

settings = get_settings()


def rescan_library(
    db: Session,
    *,
    force: bool = False,
) -> ScanResult:
    return scan_library(db=db, root=settings.music_path, force=force)


def index_library_file(
    db: Session,
    path: str,
    *,
    force: bool = False,
    download_source: str | None = None,
) -> IndexResult:
    return index_file(
        db,
        path,
        force=force,
        download_source=download_source,
    )
