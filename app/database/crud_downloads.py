from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import DownloadJob
from app.domain.download import JobStatus


def create_job(
    db: Session,
    spotify_url: str,
    title: str,
    artist: str,
) -> DownloadJob:
    job = DownloadJob(
        spotify_url=spotify_url,
        title=title,
        artist=artist,
        status=JobStatus.QUEUED,
    )

    db.add(job)
    db.commit()
    db.refresh(job)

    return job


def list_jobs(db: Session) -> list[DownloadJob]:
    return list(
        db.scalars(
            select(DownloadJob).order_by(
                DownloadJob.created_at.desc()
            )
        )
    )


def get_job(
    db: Session,
    job_id: int,
) -> DownloadJob | None:
    return db.get(DownloadJob, job_id)


def find_by_spotify_url(
    db: Session,
    spotify_url: str,
) -> DownloadJob | None:
    return db.scalar(
        select(DownloadJob).where(
            DownloadJob.spotify_url == spotify_url
        )
    )


def find_active_job_by_spotify_url(
    db: Session,
    spotify_url: str,
) -> DownloadJob | None:
    return db.scalar(
        select(DownloadJob)
        .where(
            DownloadJob.spotify_url == spotify_url,
            DownloadJob.status.in_(
                (
                    JobStatus.QUEUED,
                    JobStatus.RUNNING,
                )
            ),
        )
    )


def next_job(db: Session) -> DownloadJob | None:
    return db.scalar(
        select(DownloadJob)
        .where(DownloadJob.status == JobStatus.QUEUED)
        .order_by(DownloadJob.created_at)
    )


def update_status(
    db: Session,
    job: DownloadJob,
    status: JobStatus,
) -> DownloadJob:
    job.status = status

    if status == JobStatus.RUNNING:
        job.started_at = datetime.utcnow()

    elif status in (
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    ):
        job.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(job)

    return job


def delete_job(
    db: Session,
    job: DownloadJob,
) -> None:
    db.delete(job)
    db.commit()


def recover_running_jobs(
    db: Session,
) -> None:
    running_jobs = db.scalars(
        select(DownloadJob).where(
            DownloadJob.status == JobStatus.RUNNING
        )
    )

    for job in running_jobs:
        job.status = JobStatus.QUEUED
        job.started_at = None

    db.commit()