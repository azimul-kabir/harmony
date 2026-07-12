import time

from app.services.task_service import (
    increment_completed,
    increment_failed,
    increment_skipped,
    set_current_item,
    start_task,
)

from sqlalchemy.orm import Session

from app.core.logging import logger
from app.database.crud_downloads import (
    next_job,
    recover_running_jobs,
    update_status,
)
from app.database.models import DownloadJob
from app.database.session import SessionLocal
from app.domain.download import JobStatus
from app.domain.track import Track
from app.exceptions.library import DuplicateTrackError
from app.services.download import download_track
from app.services.library_manager import import_downloaded_track


def worker_loop() -> None:
    logger.info("Download worker started.")

    db = SessionLocal()
    try:
        recover_running_jobs(db)
    finally:
        db.close()

    while True:
        db = SessionLocal()

        try:
            job = next_job(db)

            if job is None:
                time.sleep(2)
                continue

            process_job(db, job)

        except Exception:
            logger.exception("Worker crashed while processing job.")

        finally:
            db.close()

        time.sleep(1)


def process_job(
    db: Session,
    job: DownloadJob,
) -> None:
    logger.info("Starting job #{}", job.id)

    update_status(
        db=db,
        job=job,
        status=JobStatus.RUNNING,
    )

    if job.task is not None:
        start_task(
            db=db,
            task=job.task,
        )

        set_current_item(
            db=db,
            task=job.task,
            item=job.title,
        )

    job.error = None
    db.commit()

    output_file = None

    try:
        track = Track(
            title=job.title,
            artist=job.artist,
            spotify_url=job.spotify_url,
        )

        output_file = download_track(track)

        library_file = import_downloaded_track(
            db=db,
            downloaded_file=output_file,
        )

        job.output_file = str(library_file)
        job.error = None
        db.commit()

        update_status(
            db=db,
            job=job,
            status=JobStatus.COMPLETED,
        )

        if job.task is not None:
            set_current_item(
                db=db,
                task=job.task,
                item=None,
            )

            increment_completed(
                db=db,
                task=job.task,
            )

        logger.info(
            "Finished job #{} -> {}",
            job.id,
            library_file,
        )

    except DuplicateTrackError as ex:
        logger.info(
            "Skipping duplicate: {}",
            ex,
        )

        if output_file is not None and output_file.exists():
            output_file.unlink()

        job.output_file = None
        job.error = None
        db.commit()

        update_status(
            db=db,
            job=job,
            status=JobStatus.SKIPPED,
        )

        if job.task is not None:
            set_current_item(
                db=db,
                task=job.task,
                item=None,
            )

            increment_skipped(
                db=db,
                task=job.task,
            )

    except Exception as ex:
        job.error = str(ex)
        db.commit()

        update_status(
            db=db,
            job=job,
            status=JobStatus.FAILED,
        )

        if job.task is not None:
            set_current_item(
                db=db,
                task=job.task,
                item=None,
            )

            increment_failed(
                db=db,
                task=job.task,
            )

        logger.exception(
            "Job #{} failed",
            job.id,
        )
