"""Privacy-safe read model for the Downloads operations center."""

from datetime import UTC, datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, load_only

from app.database.models import DownloadJob
from app.domain.download import JobStatus


TERMINAL_STATUSES = (
    JobStatus.COMPLETED.value, JobStatus.FAILED.value,
    JobStatus.SKIPPED.value, JobStatus.CANCELLED.value,
)
QUEUE_LIMIT = 25
HISTORY_LIMIT = 100


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC if value.tzinfo is None else value.tzinfo).isoformat().replace("+00:00", "Z")


def _job_columns():
    return load_only(DownloadJob.id, DownloadJob.status, DownloadJob.title,
                     DownloadJob.artist, DownloadJob.album, DownloadJob.created_at,
                     DownloadJob.started_at, DownloadJob.completed_at)


def _history_job(job: DownloadJob) -> dict:
    return {"id": job.id, "status": job.status, "title": job.title,
            "artist": job.artist, "album": job.album}


def get_download_snapshot(db: Session, *, queue_limit: int = QUEUE_LIMIT,
                          history_limit: int = HISTORY_LIMIT) -> dict:
    """Return bounded, deterministic queue state without download-sensitive fields.

    The waiting order exactly mirrors ``claim_next_job``: oldest created job,
    with the primary key breaking timestamp ties.
    """
    queue_limit = max(1, min(queue_limit, QUEUE_LIMIT))
    history_limit = max(1, min(history_limit, HISTORY_LIMIT))
    counts = db.execute(select(
        func.coalesce(func.sum(case((DownloadJob.status == JobStatus.RUNNING.value, 1), else_=0)), 0),
        func.coalesce(func.sum(case((DownloadJob.status == JobStatus.QUEUED.value, 1), else_=0)), 0),
        func.coalesce(func.sum(case((DownloadJob.status == JobStatus.PAUSED.value, 1), else_=0)), 0),
        func.coalesce(func.sum(case((DownloadJob.status == JobStatus.COMPLETED.value, 1), else_=0)), 0),
        # The Downloads "failed" filter deliberately includes cancelled jobs.
        func.coalesce(func.sum(case((DownloadJob.status.in_((JobStatus.FAILED.value, JobStatus.CANCELLED.value)), 1), else_=0)), 0),
        func.coalesce(func.sum(case((DownloadJob.status == JobStatus.CANCELLED.value, 1), else_=0)), 0),
    )).one()

    active = db.scalars(select(DownloadJob).options(_job_columns()).where(
        DownloadJob.status == JobStatus.RUNNING.value
    ).order_by(DownloadJob.started_at.asc(), DownloadJob.id.asc()).limit(queue_limit)).all()
    queued = db.scalars(select(DownloadJob).options(_job_columns()).where(
        DownloadJob.status == JobStatus.QUEUED.value
    ).order_by(DownloadJob.created_at.asc(), DownloadJob.id.asc()).limit(queue_limit)).all()
    paused = db.scalars(select(DownloadJob).options(_job_columns()).where(
        DownloadJob.status == JobStatus.PAUSED.value
    ).order_by(DownloadJob.created_at.asc(), DownloadJob.id.asc()).limit(queue_limit)).all()
    history = db.scalars(select(DownloadJob).options(_job_columns()).order_by(
        DownloadJob.id.desc()).limit(history_limit)).all()

    return {
        "counts": dict(zip(("running", "queued", "paused", "completed", "failed", "cancelled"), map(int, counts))),
        "active": [{"id": j.id, "title": j.title, "artist": j.artist, "status": j.status,
                    "progress": None, "stage": None, "worker_slot": None, "started_at": _timestamp(j.started_at)} for j in active],
        "queued": [{"id": j.id, "title": j.title, "artist": j.artist, "position": i,
                    "status": j.status, "created_at": _timestamp(j.created_at)} for i, j in enumerate(queued, 1)],
        "paused": [{"id": j.id, "title": j.title, "artist": j.artist, "position": i,
                    "status": j.status, "created_at": _timestamp(j.created_at)} for i, j in enumerate(paused, 1)],
        "jobs": [_history_job(job) for job in history],
    }
