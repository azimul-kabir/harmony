import json
import threading
from datetime import UTC, datetime

from sqlalchemy import select, text, or_
from sqlalchemy.orm import Session

from app.database.models import DownloadJob, Task
from app.domain.download import JobStatus
from app.domain.task import TaskStatus
from app.domain.track import Track
from app.services.download_telemetry import utcnow_naive


# SQLite only permits one writer at a time.  All download workers live in this
# process, so serialize the very small claim transaction rather than making
# every worker race for ``BEGIN IMMEDIATE`` (and exhaust SQLite's busy timeout).
_job_claim_lock = threading.Lock()


def create_job(
    db: Session,
    track: Track,
    task_id: int | None = None,
    queue_position: int | None = None,
    *,
    commit: bool = True,
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
        duration=track.duration,
        spotify_artist_ids=json.dumps(track.spotify_artist_ids),
        genre_provenance=track.genre_provenance,
        status=JobStatus.QUEUED.value,
    )

    db.add(job)
    if commit:
        db.commit()
        db.refresh(job)
    else:
        db.flush()

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
    with _job_claim_lock:
        try:
            # Reserve the writer before reading so two workers cannot select
            # the same queued row.  Keep the reservation inside the protected
            # block through commit/rollback.
            db.execute(text("BEGIN IMMEDIATE"))

            # Check if the job's parent task is not active (paused or cancelled)
            # If the job has no parent task (a standalone single track download), allow it.
            job = db.scalar(
                select(DownloadJob)
                .outerjoin(Task, DownloadJob.task_id == Task.id)
                .where(
                    DownloadJob.status == JobStatus.QUEUED.value,
                    or_(
                        DownloadJob.next_attempt_at.is_(None),
                        DownloadJob.next_attempt_at <= utcnow_naive(),
                    ),
                    or_(
                        Task.id.is_(None),
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
            job.attempt_count += 1
            job.next_attempt_at = None
            job.started_at = datetime.now(UTC)
            job.heartbeat_at = utcnow_naive()
            job.pipeline_stage = "claimed"
            job.progress_percent = 0

            db.commit()
            db.refresh(job)

            return job

        except Exception:
            # BEGIN IMMEDIATE can itself fail, so it must be covered by the
            # rollback path as well as the SELECT/update operations.
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
        job.next_attempt_at = None
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
