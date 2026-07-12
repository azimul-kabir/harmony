from app.domain.track import Track

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import DownloadJob
from app.domain.download import JobStatus


def create_job(
    db: Session,
    track: Track,
    task_id: int | None = None,
) -> DownloadJob:
    job = DownloadJob(
        task_id=task_id,
        spotify_url=track.spotify_url,
        spotify_track_id=track.spotify_track_id,
        spotify_album_id=track.spotify_album_id,
        title=track.title,
        artist=track.artist,
        album=track.album,
        album_artist=track.album_artist,
        track=track.track,
        disc=track.disc,
        year=track.year,
        isrc=track.isrc,
        status=JobStatus.QUEUED.value,
    )

    db.add(job)
    db.commit()
    db.refresh(job)

    return job


def list_jobs(
    db: Session,
) -> list[DownloadJob]:
    return list(db.scalars(select(DownloadJob).order_by(DownloadJob.created_at.desc())))


def get_job(
    db: Session,
    job_id: int,
) -> DownloadJob | None:
    return db.get(DownloadJob, job_id)


def find_by_spotify_url(
    db: Session,
    spotify_url: str,
) -> DownloadJob | None:
    return db.scalar(select(DownloadJob).where(DownloadJob.spotify_url == spotify_url))


def find_active_job_by_spotify_url(
    db: Session,
    spotify_url: str,
) -> DownloadJob | None:
    return db.scalar(
        select(DownloadJob).where(
            DownloadJob.spotify_url == spotify_url,
            DownloadJob.status.in_(
                (
                    JobStatus.QUEUED.value,
                    JobStatus.RUNNING.value,
                )
            ),
        )
    )


def next_job(
    db: Session,
) -> DownloadJob | None:
    return db.scalar(
        select(DownloadJob)
        .where(DownloadJob.status == JobStatus.QUEUED.value)
        .order_by(DownloadJob.created_at)
    )


def update_status(
    db: Session,
    job: DownloadJob,
    status: JobStatus,
) -> DownloadJob:
    job.status = status.value

    if status == JobStatus.RUNNING:
        job.started_at = datetime.now(UTC)

    elif status in (
        JobStatus.COMPLETED,
        JobStatus.SKIPPED,
        JobStatus.FAILED,
    ):
        job.completed_at = datetime.now(UTC)

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
        select(DownloadJob).where(DownloadJob.status == JobStatus.RUNNING.value)
    )

    for job in running_jobs:
        job.status = JobStatus.QUEUED.value
        job.started_at = None

    db.commit()
