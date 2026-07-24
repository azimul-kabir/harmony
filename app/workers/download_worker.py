import time
import threading
import json

from sqlalchemy.orm import Session

from app.core.logging import logger
from app.database.crud_downloads import (
    claim_next_job,
    recover_running_jobs,
    update_status,
)
from app.database.models import DownloadJob
from app.database.session import SessionLocal
from app.domain.download import JobStatus
from app.domain.download_outcome import DownloadCancelled, DownloadFailed, DownloadOutcome, DownloadSkipped, classify_unexpected
from app.domain.task import TaskStatus
from app.domain.track import Track
from app.exceptions.library import DuplicateTrackError
from app.services.download import download_track
from app.services.download_telemetry import heartbeat_ticker, update_telemetry
from app.services.spotify.genres import enrich_tracks
from app.services.genre_tags import write_genres
from app.services.library_manager import import_downloaded_track
from app.services.playlist_manager import export_all_m3us
from app.services.task_service import (
    increment_completed,
    increment_failed,
    increment_skipped,
    set_current_item,
    start_task,
)

def worker_loop() -> None:
    logger.info(
        "{} started.",
        threading.current_thread().name,
    )
    db = SessionLocal()
    try:
        recover_running_jobs(db)
    finally:
        db.close()
        
    while True:
        db = SessionLocal()
        try:
            job = claim_next_job(db)
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
    logger.info("Preparing job #{}", job.id)
    
    # --- PRE-FLIGHT CHECK ---
    # Refresh the database state to catch last-second UI clicks
    db.refresh(job)
    if job.task is not None:
        db.refresh(job.task)
        # If the user clicked Pause, put the song back in the queue and stop execution.
        if job.task.status == TaskStatus.PAUSED.value:
            logger.info("Queue is PAUSED. Returning job #{} to queue.", job.id)
            update_status(db=db, job=job, status=JobStatus.QUEUED)
            return
            
        # If the user clicked Cancel, mark it cancelled and stop execution.
        if job.task.status == TaskStatus.CANCELLED.value:
            logger.info("Task was CANCELLED. Aborting job #{}.", job.id)
            _record_outcome(db, job, JobStatus.CANCELLED, "cancelled_before_start", "The parent task was cancelled before this download started.", "preflight", "harmony", False)
            update_status(db=db, job=job, status=JobStatus.CANCELLED)
            return
            
    # If the individual job was cancelled
    if job.status == JobStatus.CANCELLED.value:
        logger.info("Job #{} was individually CANCELLED.", job.id)
        return
    # ------------------------
    
    logger.info("Starting job #{}", job.id)
    
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
    job.error_message = None
    update_telemetry(
        db,
        job,
        stage="preparing",
        progress_percent=5,
        worker_name=threading.current_thread().name,
    )
    
    output_file = None
    ticker = heartbeat_ticker(job.id)
    ticker.__enter__()
    try:
        # Build the Track domain object, carrying the cover_url and extended metadata forward
        track = Track(
            title=job.title,
            artist=job.artist,
            album=job.album,
            album_artist=job.album_artist,
            track=job.track,
            cover_url=job.cover_url,  # <-- NEW: Carry artwork URL to engine
            spotify_track_id=job.spotify_track_id, 
            spotify_url=job.source_url, 
            source_provider=job.source_provider or "spotify",
            source_item_id=job.source_item_id,
            source_url=job.source_url,
            genre=job.genre,
            spotify_artist_ids=json.loads(job.spotify_artist_ids or "[]"),
            genre_provenance=job.genre_provenance,
        )
        # A queued job may predate genre support; resolve safely at execution.
        if not track.genre:
            update_telemetry(db, job, stage="metadata", progress_percent=10)
            # Enrichment is optional; a provider outage must not fail audio.
            try:
                enrich_tracks([track], job_id=job.id)
            except Exception:
                logger.warning("Optional genre enrichment failed for job #{}", job.id)
            # Persist successful pre-flight enrichment for retries and future jobs.
            if track.genre:
                job.genre = track.genre
                job.genre_provenance = track.genre_provenance
                db.commit()
        update_telemetry(db, job, stage="downloading", progress_percent=None)
        output_file = download_track(track, job.id)
        if _cancelled(db, job, output_file):
            return
        update_telemetry(db, job, stage="tagging", progress_percent=80)
        if track.genre:
            try:
                write_genres(output_file, track.genre.split(";"))
            except Exception:
                logger.warning("Optional genre tagging failed for job #{}", job.id)
        if _cancelled(db, job, output_file):
            return
        
        update_telemetry(db, job, stage="importing", progress_percent=90)
        library_file = import_downloaded_track(
            db=db,
            downloaded_file=output_file,
            cover_url=job.cover_url,  # <-- NEW: Pass to library import manager
            genre_provenance=track.genre_provenance,
            download_source=track.source_provider,
        )
        if _cancelled(db, job, None):
            return
        job.output_file = str(library_file)
        job.error = None
        db.commit()
        
        _record_outcome(db, job, JobStatus.COMPLETED, "completed", "Download completed.", "complete", job.source_provider or "spotdl", False)
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
        
        # This is post-download maintenance: never turn a terminal success into a failure.
        try:
            export_all_m3us(db)
        except Exception:
            logger.warning("Playlist export failed after completed job #{}", job.id)
        
    except DuplicateTrackError as ex:
        logger.info(
            "Skipping duplicate: {}",
            ex,
        )
        if output_file is not None and output_file.exists():
            output_file.unlink()
            
        _finish_with_outcome(db, job, JobStatus.SKIPPED, DownloadSkipped("duplicate_in_library", "This track is already in your library.", "preflight", technical_detail=type(ex).__name__))
    except DownloadSkipped as outcome:
        _finish_with_outcome(db, job, JobStatus.SKIPPED, outcome)
    except DownloadCancelled as outcome:
        _finish_with_outcome(db, job, JobStatus.CANCELLED, outcome)
    except DownloadFailed as outcome:
        _finish_with_outcome(db, job, JobStatus.FAILED, outcome)
    except Exception as ex:
        # Typed outcomes above deliberately precede this broad safety net.
        outcome = classify_unexpected(ex)
        _finish_with_outcome(db, job, JobStatus.SKIPPED if isinstance(outcome, DownloadSkipped) else JobStatus.FAILED, outcome)
        if not isinstance(outcome, DownloadSkipped):
            logger.exception("Job #{} failed", job.id)
    finally:
        ticker.__exit__(None, None, None)


def _record_outcome(db, job, status, code, message, stage, provider, retryable, technical_detail=None):
    """Persist a terminal outcome once; callers must not overwrite it later."""
    if job.status in {JobStatus.COMPLETED.value, JobStatus.SKIPPED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value}:
        return
    job.reason_code, job.reason_message = code, message
    job.failure_stage, job.provider, job.retryable = stage, provider, retryable
    job.technical_detail = technical_detail
    db.commit()
    logger.info("download_terminal download_id={} status={} reason_code={} stage={} provider={} retryable={}", job.id, status.value, code, stage, provider, retryable)


def _cancelled(db, job, output_file):
    db.refresh(job)
    if job.status != JobStatus.CANCELLED.value:
        return False
    if output_file is not None and output_file.exists():
        try:
            output_file.unlink()
        except OSError:
            logger.warning("Cancelled job #{} output cleanup failed", job.id)
    return True


def _finish_with_outcome(db, job, status, outcome):
    db.refresh(job)
    if job.status == JobStatus.CANCELLED.value:
        return
    _record_outcome(db, job, status, outcome.reason_code, outcome.message, outcome.stage, outcome.provider, outcome.retryable, outcome.technical_detail)
    update_status(db=db, job=job, status=status)
    if job.task is not None:
        set_current_item(db=db, task=job.task, item=None)
        {JobStatus.SKIPPED: increment_skipped, JobStatus.FAILED: increment_failed}.get(status, lambda **_: None)(db=db, task=job.task)
