import time
from datetime import datetime

from app.core.logging import logger
from app.database.crud_downloads import (
    next_job,
    recover_running_jobs,
)
from app.database.models import DownloadJob
from app.database.session import SessionLocal
from app.domain.download import JobStatus
from app.domain.track import Track
from app.services.download import download_track
from app.services.library_import import import_file


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

    job.status = JobStatus.RUNNING
    job.started_at = datetime.utcnow()
    job.error = None

    db.commit()

    try:
        track = Track(
            title=job.title,
            artist=job.artist,
            spotify_url=job.spotify_url,
        )

        output_file = download_track(track)

        job.output_file = str(output_file)

        #
        # Automatically import the downloaded file
        # into the Harmony library.
        #
        try:
            import_file(
                db=db,
                path=output_file,
            )
        except Exception:
            logger.exception(
                "Failed to import downloaded file: {}",
                output_file,
            )

        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.utcnow()

        db.commit()

        logger.info("Finished job #{}", job.id)

    except Exception as ex:
        job.status = JobStatus.FAILED
        job.error = str(ex)
        job.completed_at = datetime.utcnow()

        db.commit()

        logger.exception("Job #{} failed", job.id)