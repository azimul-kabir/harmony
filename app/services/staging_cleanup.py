"""Conservative cleanup for resumable download staging files."""

from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from app.core.logging import logger
from app.database.models import DownloadJob
from app.services.download_telemetry import utcnow_naive


STAGING_RETENTION_DAYS = 7
ACTIVE_STATUSES = frozenset({"queued", "running", "paused"})


def cleanup_staging_downloads(
    db,
    root: Path,
    *,
    retention_days: int = STAGING_RETENTION_DAYS,
) -> int:
    """Delete only old, unprotected regular files beneath the staging root."""
    root = root.resolve()
    if not root.is_dir():
        return 0
    cutoff = utcnow_naive() - timedelta(days=max(1, retention_days))
    protected: set[Path] = set()
    rows = db.execute(
        select(
            DownloadJob.output_file,
            DownloadJob.status,
            DownloadJob.updated_at,
        ).where(DownloadJob.output_file.is_not(None))
    ).all()
    for output_file, status, updated_at in rows:
        if status not in ACTIVE_STATUSES and not (
            status == "failed" and updated_at is not None and updated_at >= cutoff
        ):
            continue
        try:
            candidate = Path(output_file).resolve()
            candidate.relative_to(root)
        except (OSError, ValueError):
            continue
        protected.add(candidate)

    removed = 0
    for candidate in root.rglob("*"):
        if candidate.is_symlink() or not candidate.is_file():
            continue
        try:
            resolved = candidate.resolve()
            resolved.relative_to(root)
            modified = candidate.stat().st_mtime
        except (OSError, ValueError):
            continue
        if resolved in protected or modified >= cutoff.timestamp():
            continue
        try:
            candidate.unlink()
            removed += 1
        except OSError:
            logger.warning("Could not remove expired download staging file")
    if removed:
        logger.info("Removed {} expired download staging files", removed)
    return removed
