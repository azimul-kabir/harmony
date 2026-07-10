import time

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
    db,
    job: DownloadJob,
) -> None:
    logger.info("Starting job #{}", job.id)

    update_status(
        db=db,
        job=job,
        status=JobStatus.RUNNING,
    )

    job.error = None
    db.commit()

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

        db.commit()

        update_status(
            db=db,
            job=job,
            status=JobStatus.COMPLETED,
        )

        logger.info("Finished job #{}", job.id)

    except FileExistsError as ex:
        job.error = str(ex)
        db.commit()

        update_status(
            db=db,
            job=job,
            status=JobStatus.SKIPPED,
        )

        logger.info(
            "Skipped job #{} because the track already exists.",
            job.id,
        )

    except Exception as ex:
        job.error = str(ex)
        db.commit()

        update_status(
            db=db,
            job=job,
            status=JobStatus.FAILED,
        )

        logger.exception("Job #{} failed", job.id)