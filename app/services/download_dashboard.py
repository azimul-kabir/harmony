"""Read model for the live Downloads command center."""

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.database.models import DownloadJob
from app.domain.download import JobStatus


TERMINAL_STATUSES = (
    JobStatus.COMPLETED.value,
    JobStatus.FAILED.value,
    JobStatus.SKIPPED.value,
    JobStatus.CANCELLED.value,
)


def get_download_snapshot(db: Session, *, limit: int = 100) -> dict:
    """Return bounded jobs plus global, actionable queue counts."""
    counts = db.execute(
        select(
            func.coalesce(func.sum(case((DownloadJob.status == JobStatus.RUNNING.value, 1), else_=0)), 0),
            func.coalesce(func.sum(case((DownloadJob.status == JobStatus.QUEUED.value, 1), else_=0)), 0),
            func.coalesce(func.sum(case((DownloadJob.status == JobStatus.COMPLETED.value, 1), else_=0)), 0),
            func.coalesce(func.sum(case((DownloadJob.status.in_((JobStatus.FAILED.value, JobStatus.CANCELLED.value)), 1), else_=0)), 0),
        )
    ).one()
    jobs = db.scalars(
        select(DownloadJob).order_by(DownloadJob.id.desc()).limit(limit)
    ).all()
    return {
        "summary": {
            "running": int(counts[0]),
            "queued": int(counts[1]),
            "completed": int(counts[2]),
            "attention": int(counts[3]),
        },
        "jobs": [
            {
                "id": job.id,
                "status": job.status,
                "title": job.title,
                "artist": job.artist,
                "album": job.album,
                "spotify_url": job.spotify_url,
                "cover_url": job.cover_url,
                "error": job.error,
            }
            for job in jobs
        ],
    }
