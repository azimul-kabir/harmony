"""Safe, privacy-preserving bulk operations for download records."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import DownloadJob
from app.domain.download import JobStatus


MAX_BULK_IDS = 100
ALLOWED_BULK_ACTIONS = frozenset({
    "retry", "cancel", "clear_history", "clear_completed_history",
    "clear_failed_cancelled_history",
})
TERMINAL = frozenset((JobStatus.COMPLETED.value, JobStatus.FAILED.value,
                      JobStatus.SKIPPED.value, JobStatus.CANCELLED.value))


def capabilities(job: DownloadJob) -> dict[str, bool]:
    """Expose action permissions derived from the authoritative job state."""
    return {
        "retry": job.status in (JobStatus.FAILED.value, JobStatus.CANCELLED.value),
        "cancel": job.status in (JobStatus.QUEUED.value, JobStatus.RUNNING.value),
        "pause": False,
        "resume": False,
        "clear_history": job.status in TERMINAL,
    }


def _eligible(action: str, job: DownloadJob) -> bool:
    if action == "retry":
        return capabilities(job)["retry"]
    if action == "cancel":
        return capabilities(job)["cancel"]
    return capabilities(job)["clear_history"]


def run_bulk_action(db: Session, action: str, download_ids: list[int]) -> dict[str, int | str]:
    """Apply an allowlisted action and return aggregate-only, safe feedback."""
    if action not in ALLOWED_BULK_ACTIONS:
        raise ValueError("Unsupported bulk action.")
    if len(download_ids) > MAX_BULK_IDS:
        raise ValueError(f"A bulk action can include at most {MAX_BULK_IDS} downloads.")

    requested = len(set(download_ids))
    query = select(DownloadJob)
    if action == "clear_completed_history":
        query = query.where(DownloadJob.status.in_((JobStatus.COMPLETED.value, JobStatus.SKIPPED.value)))
        requested = db.scalar(select(func.count()).select_from(DownloadJob).where(DownloadJob.status.in_((JobStatus.COMPLETED.value, JobStatus.SKIPPED.value)))) or 0
    elif action == "clear_failed_cancelled_history":
        query = query.where(DownloadJob.status.in_((JobStatus.FAILED.value, JobStatus.CANCELLED.value)))
        requested = db.scalar(select(func.count()).select_from(DownloadJob).where(DownloadJob.status.in_((JobStatus.FAILED.value, JobStatus.CANCELLED.value)))) or 0
    else:
        ids = list(set(download_ids))
        query = query.where(DownloadJob.id.in_(ids)) if ids else query.where(False)

    jobs = list(db.scalars(query))
    eligible = [job for job in jobs if _eligible(action, job)]
    succeeded = 0
    now = datetime.now(UTC)
    try:
        for job in eligible:
            if action == "retry":
                job.status = JobStatus.QUEUED.value
                job.started_at = None
                job.completed_at = None
            elif action == "cancel":
                job.status = JobStatus.CANCELLED.value
                job.completed_at = now
            else:
                db.delete(job)
            succeeded += 1
        db.commit()
    except Exception:
        db.rollback()
        # Do not expose exception contents or record identifiers.
        return {"action": action, "requested": requested, "eligible": len(eligible),
                "succeeded": 0, "skipped": requested - len(eligible),
                "failed": len(eligible), "result_code": "failed"}

    skipped = max(0, requested - len(eligible))
    return {"action": action, "requested": requested, "eligible": len(eligible),
            "succeeded": succeeded, "skipped": skipped, "failed": 0,
            "result_code": "completed" if not skipped else "partial"}
