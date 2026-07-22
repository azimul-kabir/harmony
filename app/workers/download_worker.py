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
from app.domain.task import TaskStatus
from app.domain.track import Track
from app.exceptions.library import DuplicateTrackError
from app.services.download import download_track
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
    db.commit()
    
    output_file = None
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
            genre=job.genre,
            spotify_artist_ids=json.loads(job.spotify_artist_ids or "[]"),
            genre_provenance=job.genre_provenance,
        )
        # A queued job may predate genre support; resolve safely at execution.
        if not track.genre:
            enrich_tracks([track], job_id=job.id)
            # Persist successful pre-flight enrichment for retries and future jobs.
            if track.genre:
                job.genre = track.genre
                job.genre_provenance = track.genre_provenance
                db.commit()
        output_file = download_track(track)
        if track.genre:
            write_genres(output_file, track.genre.split(";"))
        
        library_file = import_downloaded_track(
            db=db,
            downloaded_file=output_file,
            cover_url=job.cover_url,  # <-- NEW: Pass to library import manager
            genre_provenance=track.genre_provenance,
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
        
        # Auto-Export M3U so Navidrome immediately sees the newly imported track
        export_all_m3us(db)
        
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
