import errno
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import logger
from app.services.library_scanner import IndexResult, ScanResult, index_file, scan_library

settings = get_settings()


def prune_empty_parent_directories(
    deleted_file_path: str | Path,
    music_root: str | Path,
) -> None:
    """Remove empty ancestors of a deleted file without removing the music root."""
    root = Path(music_root).resolve()
    deleted_path = Path(deleted_file_path).resolve()
    if deleted_path == root or not deleted_path.is_relative_to(root):
        logger.warning(
            "Refusing to prune directories for path outside music root: {}",
            deleted_file_path,
        )
        return

    current = deleted_path.parent
    while current != root:
        # Resolve every ancestor before operating on it so a replaced symlink
        # cannot redirect cleanup outside the configured library.
        resolved_current = current.resolve()
        if resolved_current == root or not resolved_current.is_relative_to(root):
            logger.warning(
                "Stopped empty-directory pruning at unsafe path: {}",
                current,
            )
            return
        try:
            # rmdir is the emptiness check. It is atomic with respect to files
            # created by another worker, unlike list-then-remove traversal.
            resolved_current.rmdir()
        except FileNotFoundError:
            pass
        except OSError as error:
            if error.errno in {errno.ENOTEMPTY, errno.EEXIST}:
                return
            logger.warning(
                "Could not prune empty library directory {}: {}",
                resolved_current,
                error,
            )
            return
        current = resolved_current.parent


def delete_library_file(
    path: str | Path,
    music_root: str | Path | None = None,
) -> Path:
    """Delete one managed file and best-effort prune its empty ancestors."""
    root = Path(music_root or settings.music_path).resolve()
    candidate = Path(path).resolve()
    if candidate == root or not candidate.is_relative_to(root):
        raise ValueError("Path must remain inside the configured music folder")

    try:
        candidate.unlink()
    except FileNotFoundError:
        return candidate

    # Cleanup is deliberately non-fatal once the actual file deletion worked.
    try:
        prune_empty_parent_directories(candidate, root)
    except Exception as error:  # pragma: no cover - defensive helper boundary
        logger.warning(
            "Could not clean up directories after deleting {}: {}",
            candidate,
            error,
        )
    return candidate


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
