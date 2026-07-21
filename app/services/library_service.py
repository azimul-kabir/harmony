from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.library_scanner import IndexResult, ScanResult, index_file, scan_library

settings = get_settings()


def managed_library_path(path: str | Path) -> Path:
    """Resolve a path and reject files outside the configured music root."""
    root = Path(settings.music_path).resolve()
    candidate = Path(path).resolve()
    if candidate != root and not candidate.is_relative_to(root):
        raise ValueError("Path must remain inside the configured music folder")
    return candidate


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
        managed_library_path(path),
        force=force,
        download_source=download_source,
    )
