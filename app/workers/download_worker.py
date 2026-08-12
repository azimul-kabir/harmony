import time
import threading
import json
from datetime import timedelta
from pathlib import Path

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.logging import logger
from app.core.config import get_settings
from app.database.crud_downloads import (
    claim_next_job,
    recover_running_jobs,
    update_status,
)
from app.database.crud import find_song, link_song_source
from app.database.models import DownloadJob, Song
from app.database.session import SessionLocal
from app.domain.download import JobStatus
from app.domain.download_outcome import DownloadCancelled, DownloadFailed, DownloadOutcome, DownloadSkipped, classify_unexpected
from app.domain.task import TaskStatus, TaskType
from app.domain.track import Track
from app.exceptions.library import DuplicateTrackError
from app.services.download import download_track
from app.services import settings_service
from app.providers.download_sources import get_source
from app.services.download_telemetry import heartbeat_ticker, update_telemetry, utcnow_naive
from app.services.genre_tags import write_genres
from app.services.library_manager import import_downloaded_track
from app.services.library_scanner import index_file
from app.services.playlist_manager import export_m3us_for_source_track
from app.services.navidrome_playlist_sync import navidrome_playlist_reimport
from app.services.task_service import (
    increment_completed,
    increment_failed,
    increment_skipped,
    reconcile_stalled_playlist_tasks,
    set_current_item,
    start_task,
)

MAX_DOWNLOAD_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (15, 60)
RATE_LIMIT_DELAYS_SECONDS = (60, 180)

def worker_loop() -> None:
    logger.info(
        "{} started.",
        threading.current_thread().name,
    )
    db = SessionLocal()
    try:
        recover_running_jobs(db)
        repaired_task_ids = reconcile_stalled_playlist_tasks(db)
        for task_id in repaired_task_ids:
            navidrome_playlist_reimport.schedule(task_id)
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
            db.rollback()
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
        acquisition_provider = job.source_provider or "spotify"
        acquisition_item_id = job.source_item_id
        acquisition_url = job.source_url
        if job.manual_fallback_url:
            fallback_source = get_source("youtube_music")
            detected = fallback_source.detect_url(job.manual_fallback_url)
            if detected is None or detected[0] != "track":
                raise DownloadFailed(
                    "manual_fallback_invalid",
                    "The approved fallback track is no longer valid.",
                    "preflight",
                    retryable=False,
                )
            acquisition_provider = "youtube_music"
            acquisition_item_id = detected[1]
            acquisition_url = job.manual_fallback_url

        # Build the Track domain object, carrying the cover_url and extended metadata forward
        track = Track(
            title=job.title,
            artist=job.artist,
            album=job.album,
            album_artist=job.album_artist,
            track=job.track,
            disc=job.disc,
            year=job.year,
            isrc=job.isrc,
            cover_url=job.cover_url,  # <-- NEW: Carry artwork URL to engine
            spotify_track_id=job.spotify_track_id, 
            spotify_url=job.source_url, 
            source_provider=acquisition_provider,
            source_item_id=acquisition_item_id,
            source_url=acquisition_url,
            genre=job.genre,
            duration=job.duration,
            spotify_artist_ids=json.loads(job.spotify_artist_ids or "[]"),
            genre_provenance=job.genre_provenance,
        )
        output_file = _resumable_staging_file(job)
        if output_file is None:
            update_telemetry(db, job, stage="downloading", progress_percent=None)
            try:
                output_file = download_track(track, job.id)
            except ValueError as error:
                if not job.manual_fallback_url:
                    raise
                raise DownloadFailed(
                    "manual_fallback_unavailable",
                    "The approved YouTube link is unavailable. Choose a different video.",
                    "download",
                    provider="youtube_music",
                    retryable=False,
                    technical_detail=type(error).__name__,
                ) from error
            # Persist acquisition before any post-processing. If tagging or
            # import fails, a bounded retry can resume from this exact file.
            job.output_file = str(output_file.resolve())
            db.commit()
        else:
            logger.info("Resuming job #{} from staged audio", job.id)
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
        indexed_song = db.scalar(
            select(Song).where(Song.path == str(Path(library_file).resolve()))
        )
        if indexed_song is not None:
            link_song_source(
                db,
                indexed_song,
                acquisition_provider,
                acquisition_item_id,
            )
            if job.manual_fallback_url:
                link_song_source(
                    db,
                    indexed_song,
                    job.source_provider or "spotify",
                    job.source_item_id or job.spotify_track_id,
                )
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
            export_m3us_for_source_track(
                db,
                job.source_provider or "spotify",
                job.source_item_id,
                job.spotify_track_id,
            )
        except Exception:
            logger.warning("Playlist export failed after completed job #{}", job.id)
        _schedule_navidrome_reimport(job)
        
    except DuplicateTrackError as ex:
        logger.info(
            "Skipping duplicate: {}",
            ex,
        )
        if output_file is not None and output_file.exists():
            output_file.unlink()

        # A late collision means the downloaded metadata produced a path that
        # preflight could not predict. Index that existing file and remember
        # the provider identity so this and every future playlist can use it.
        existing_path = getattr(ex, "existing_path", None)
        if existing_path is not None:
            try:
                indexed = index_file(db, existing_path, force=True)
                song = db.get(Song, indexed.song_id) if indexed.song_id else None
                if song is not None:
                    link_song_source(
                        db,
                        song,
                        job.source_provider or "spotify",
                        job.source_item_id or job.spotify_track_id,
                    )
                    db.commit()
                    export_m3us_for_source_track(
                        db,
                        job.source_provider or "spotify",
                        job.source_item_id,
                        job.spotify_track_id,
                    )
            except Exception:
                db.rollback()
                logger.exception(
                    "Failed to reconcile duplicate library file for job #{}",
                    job.id,
                )
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


def _resumable_staging_file(job: DownloadJob) -> Path | None:
    """Return a safe acquired file from a prior attempt, never a library path."""
    if not job.output_file:
        return None
    candidate = Path(job.output_file)
    try:
        resolved = candidate.resolve(strict=True)
        staging = Path(get_settings().staging_path).resolve(strict=True)
        resolved.relative_to(staging)
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() else None


def _finish_with_outcome(db, job, status, outcome):
    # Database errors raised by telemetry/heartbeat updates can leave the
    # transaction inactive.  Recover it before refreshing and finalizing the
    # job; otherwise one transient SQLite lock strands the parent task at
    # 99/100 indefinitely.
    if not db.is_active:
        db.rollback()
    db.refresh(job)
    if job.status == JobStatus.CANCELLED.value:
        return
    if status == JobStatus.FAILED and outcome.reason_code in {
        "exact_match_unavailable", "fallback_match_unavailable", "provider_no_match"
    }:
        owned_song = find_song(
            db,
            title=job.title,
            artist=job.artist,
            album=job.album,
            spotify_track_id=job.spotify_track_id,
            isrc=job.isrc,
        )
        if owned_song is not None and owned_song.availability_status != "missing":
            link_song_source(
                db,
                owned_song,
                job.source_provider or "spotify",
                job.source_item_id or job.spotify_track_id,
            )
            db.commit()
            status = JobStatus.SKIPPED
            outcome = DownloadSkipped(
                "duplicate_in_library",
                "This track is already in your library.",
                "preflight",
                technical_detail="library_identity_reconciled",
            )
    if status == JobStatus.FAILED and _schedule_retry(db, job, outcome):
        return
    _record_outcome(db, job, status, outcome.reason_code, outcome.message, outcome.stage, outcome.provider, outcome.retryable, outcome.technical_detail)
    update_status(db=db, job=job, status=status)
    if job.task is not None:
        set_current_item(db=db, task=job.task, item=None)
        {JobStatus.SKIPPED: increment_skipped, JobStatus.FAILED: increment_failed}.get(status, lambda **_: None)(db=db, task=job.task)
        _schedule_navidrome_reimport(job)


def _schedule_retry(db, job, outcome) -> bool:
    """Delay transient failures without blocking a download worker thread."""
    downloads = settings_service.get_settings_by_category(db, "downloads")
    enabled = bool(downloads.get("retry_failed", True))
    if not enabled or not outcome.retryable or job.attempt_count >= MAX_DOWNLOAD_ATTEMPTS:
        return False

    attempt = max(1, job.attempt_count)
    delays = (
        RATE_LIMIT_DELAYS_SECONDS
        if outcome.reason_code == "provider_rate_limited"
        else RETRY_DELAYS_SECONDS
    )
    delay = delays[min(attempt - 1, len(delays) - 1)]
    job.reason_code = outcome.reason_code
    job.reason_message = outcome.message
    job.failure_stage = outcome.stage
    job.provider = outcome.provider
    job.retryable = True
    job.technical_detail = outcome.technical_detail
    job.status = JobStatus.QUEUED.value
    job.started_at = None
    job.completed_at = None
    job.next_attempt_at = utcnow_naive() + timedelta(seconds=delay)
    job.pipeline_stage = "retry_wait"
    job.progress_percent = None
    job.heartbeat_at = utcnow_naive()
    job.worker_name = None
    job.bytes_downloaded = None
    job.bytes_total = None
    job.transfer_rate_bps = None
    job.eta_seconds = None
    if job.task is not None:
        set_current_item(db=db, task=job.task, item=None)
    if outcome.reason_code == "provider_rate_limited":
        _cool_down_queued_provider_jobs(
            db,
            source_provider=job.source_provider or "spotify",
            until=job.next_attempt_at,
            exclude_job_id=job.id,
        )
    db.commit()
    logger.info(
        "download_retry_scheduled download_id={} attempt={} max_attempts={} "
        "delay_seconds={} reason_code={}",
        job.id,
        attempt,
        MAX_DOWNLOAD_ATTEMPTS,
        delay,
        outcome.reason_code,
    )
    return True


def _cool_down_queued_provider_jobs(
    db: Session,
    *,
    source_provider: str,
    until,
    exclude_job_id: int,
) -> None:
    """Persist a provider-wide pause while allowing other sources to proceed."""
    db.execute(
        update(DownloadJob)
        .where(
            DownloadJob.id != exclude_job_id,
            DownloadJob.status == JobStatus.QUEUED.value,
            DownloadJob.source_provider == source_provider,
            or_(
                DownloadJob.next_attempt_at.is_(None),
                DownloadJob.next_attempt_at < until,
            ),
        )
        .values(next_attempt_at=until, pipeline_stage="provider_cooldown")
    )


def _schedule_navidrome_reimport(job: DownloadJob) -> None:
    task = job.task
    if (
        task is not None
        and task.task_type == TaskType.PLAYLIST_SYNC.value
        and task.status in {
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
        }
    ):
        navidrome_playlist_reimport.schedule(task.id)
