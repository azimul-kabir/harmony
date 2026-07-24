from app.domain.track import Track
import json

from datetime import UTC, datetime

from sqlalchemy import select, text, or_
from sqlalchemy.orm import Session

from app.database.models import DownloadJob, Task
from app.domain.download import JobStatus
from app.domain.task import TaskStatus
from app.services.download_telemetry import utcnow_naive


def create_job(
    db: Session,
    track: Track,
    task_id: int | None = None,
    queue_position: int | None = None,
) -> DownloadJob:
    job = DownloadJob(
        task_id=task_id,
        spotify_url=track.source_url or track.spotify_url,
        source_provider=track.source_provider,
        source_item_id=track.source_item_id,
        source_url=track.source_url or track.spotify_url,
        spotify_track_id=track.spotify_track_id,
        spotify_album_id=track.spotify_album_id,
        title=track.title,
        artist=track.artist,
        album=track.album,
        album_artist=track.album_artist,
        track=track.track,
        queue_position=queue_position,
        cover_url=track.cover_url,
        disc=track.disc,
        year=track.year,
        isrc=track.isrc,
        genre=track.genre,
        spotify_artist_ids=json.dumps(track.spotify_artist_ids),
        genre_provenance=track.genre_provenance,
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


def claim_next_job(
    db: Session,
) -> DownloadJob | None:
    # Acquire the SQLite write lock immediately.
    db.execute(text("BEGIN IMMEDIATE"))

    try:
        # Check if the job's parent task is not active (paused or cancelled)
        # If the job has no parent task (a standalone single track download), allow it.
        job = db.scalar(
            select(DownloadJob)
            .outerjoin(Task, DownloadJob.task_id == Task.id)
            .where(
                DownloadJob.status == JobStatus.QUEUED.value,
                or_(
                    Task.id == None,
                    ~Task.status.in_((TaskStatus.PAUSED.value, TaskStatus.CANCELLED.value))
                )
            )
            .order_by(DownloadJob.created_at, DownloadJob.id)
            .limit(1)
        )

        if job is None:
            db.commit()
            return None

        job.status = JobStatus.RUNNING.value
        job.started_at = datetime.now(UTC)
        job.heartbeat_at = utcnow_naive()
        job.pipeline_stage = "claimed"
        job.progress_percent = 0

        db.commit()
        db.refresh(job)

        return job

    except Exception:
        db.rollback()
        raise


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
        JobStatus.CANCELLED, # Tracks completion time when manually aborted
    ):
        job.completed_at = datetime.now(UTC)
        job.heartbeat_at = utcnow_naive()
        job.pipeline_stage = status.value
        job.progress_percent = 100 if status == JobStatus.COMPLETED else None
        job.eta_seconds = None
        job.transfer_rate_bps = None

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
        job.heartbeat_at = None
        job.pipeline_stage = None
        job.progress_percent = None
        job.worker_name = None
        job.bytes_downloaded = None
        job.bytes_total = None
        job.transfer_rate_bps = None
        job.eta_seconds = None

    db.commit()
