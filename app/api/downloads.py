import asyncio
import json
from datetime import UTC, datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.api.schemas.download import DownloadBulkRequest, DownloadRequest
from app.database.models import DownloadJob
from app.database.session import get_db, SessionLocal
from app.exceptions.download import TrackAlreadyExistsError
from app.services.download_queue import (
    enqueue_album,
    enqueue_track,
)
from app.services.playlist_download import download_playlist
from app.services.spotify.metadata import resolve_track
from app.services.spotify.url import spotify_resource
from app.providers.download_sources import detect_source, get_source
from app.core.config import get_settings
from app.domain.download import JobStatus
from app.services.download_dashboard import (
    TERMINAL_STATUSES, download_counts, download_details, download_history,
    get_download_snapshot, serialize_outcome,
)
from app.services.download_bulk import run_bulk_action
from app.core.logging import logger
from app.services.download_processes import download_processes
from dataclasses import asdict
from app.services import settings_service

router = APIRouter(
    prefix="/api/downloads",
    tags=["downloads"],
)


def _youtube_music_enabled(db: Session) -> bool:
    settings_service.initialize_defaults(db)
    saved = settings_service.get_settings_by_category(db, "downloads")
    return bool(get_settings().youtube_music_enabled and saved.get("youtube_music_enabled", True))

@router.post("", status_code=201)
def queue_download(request: DownloadRequest, db: Session = Depends(get_db)):
    """Create durable queued work and return only safe, JSON API errors.

    Workers poll persisted jobs, so there is no in-process task dispatch which
    can make this request appear to fail after the database commit.  Keep the
    post-commit response deliberately small and guard the optional serializer:
    a presentation defect must never convert a successfully queued job into a
    misleading 500 response.
    """
    try:
        source = detect_source(request.url.strip())
        if source is not None:
            if not _youtube_music_enabled(db):
                raise HTTPException(status_code=403, detail={"code": "provider_disabled", "message": "YouTube Music downloads are disabled in Settings."})
            resource, _ = source.detect_url(request.url.strip()) or ("unsupported", "")
            if resource == "artist":
                raise HTTPException(status_code=422, detail={"code": "unsupported_youtube_music_url", "message": "Artist URLs cannot be downloaded directly. Choose a song, album, or playlist."})
            tracks = source.resolve(request.url.strip())
            if len(tracks) > get_settings().youtube_music_max_queue_items:
                raise HTTPException(status_code=422, detail={"code": "queue_limit_exceeded", "message": "This collection exceeds Harmony's queue request limit."})
            if resource == "track":
                try:
                    result = enqueue_track(db, tracks[0])
                except TrackAlreadyExistsError:
                    return {"status": "owned"}
                return {"status": result.status.value, "job_id": result.job_id}
            results = []
            for track in tracks:
                try:
                    results.append(enqueue_track(db, track))
                except TrackAlreadyExistsError:
                    continue
            return {"status": "queued", "job_ids": [result.job_id for result in results]}
        resource, _ = spotify_resource(request.url.strip())
        if resource == "track":
            track = resolve_track(request.url)
            try:
                result = enqueue_track(db=db, track=track)
            except TrackAlreadyExistsError:
                return {"status": "owned"}

            response = {"status": result.status.value, "job_id": result.job_id}
            # Validate the newly persisted job against the common outcome
            # serializer.  It must accept empty terminal fields for queued work.
            try:
                job = db.get(DownloadJob, result.job_id)
                if job is not None:
                    response["outcome"] = serialize_outcome(job)
            except Exception:
                # The commit already succeeded.  Return a valid acknowledgement
                # rather than reporting a false failure and encouraging retries.
                logger.exception("Queued download #{} could not be serialized", result.job_id)
            return response

        if resource == "album":
            results = enqueue_album(db=db, spotify_url=request.url)
            return {"status": "queued", "job_ids": [result.job_id for result in results]}

        if resource == "playlist":
            summary = download_playlist(db=db, url=request.url)
            return {"status": "queued", "summary": summary}
    except ValueError as exc:
        # URL parsing and provider validation are user-input errors, never a
        # plain-text 500.  Do not expose provider internals to the browser.
        # Preserve the long-standing Spotify validation code for legacy callers.
        raise HTTPException(status_code=422, detail={"code": "invalid_spotify_url", "message": str(exc)}) from None
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Unable to queue Spotify download")
        raise HTTPException(
            status_code=502,
            detail={"code": "download_queue_unavailable", "message": "Harmony could not queue this download. Please try again."},
        ) from None

    raise HTTPException(status_code=422, detail={"code": "unsupported_spotify_url", "message": "This Spotify URL type is not supported."})


@router.get("/search")
def search_download_source(query: str = Query(min_length=1, max_length=200), provider: str = "youtube_music", limit: int = Query(20, ge=1, le=25), db: Session = Depends(get_db)):
    """Bounded provider-neutral catalogue search; raw extractor payloads never leave Harmony."""
    if provider != "youtube_music":
        raise HTTPException(status_code=422, detail={"code": "unsupported_provider", "message": "This download source does not support catalogue search."})
    if not _youtube_music_enabled(db):
        raise HTTPException(status_code=403, detail={"code": "provider_disabled", "message": "YouTube Music downloads are disabled in Settings."})
    try:
        return {"provider": provider, "results": [asdict(result) for result in get_source(provider).search(query, limit)]}
    except ValueError as exc:
        raise HTTPException(status_code=502, detail={"code": "provider_unavailable", "message": str(exc)}) from None

@router.post("/clear", status_code=200)
def clear_history(db: Session = Depends(get_db)):
    """Deletes all completed, skipped, and failed jobs to keep the UI clean."""
    db.execute(
        delete(DownloadJob).where(
            DownloadJob.status.in_([
                *TERMINAL_STATUSES,
            ])
        )
    )
    db.commit()
    return {"status": "success"}


@router.post("/bulk")
def bulk_downloads(request: DownloadBulkRequest, db: Session = Depends(get_db)):
    """Perform only allowlisted, state-aware operations on bounded records."""
    try:
        return run_bulk_action(db, request.action, request.download_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/snapshot")
def download_snapshot(db: Session = Depends(get_db)):
    """Bounded, privacy-safe queue state for the Downloads page."""
    return get_download_snapshot(db)


@router.get("/counters")
def download_counters(db: Session = Depends(get_db)):
    """Zero-filled aggregate counts calculated from persisted download jobs."""
    return {"counts": download_counts(db)}


@router.get("/queue")
def live_download_queue(db: Session = Depends(get_db)):
    """Persisted live queue; worker memory is never required for visibility."""
    snapshot = get_download_snapshot(db, history_limit=1)
    return {"active": snapshot["active"], "queued": snapshot["queued"], "paused": snapshot["paused"]}


@router.get("/history")
def persisted_download_history(
    page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=250),
    status: str | None = None, search: str | None = None, db: Session = Depends(get_db),
):
    """Paginated persisted track history, independent of parent task lifecycle."""
    return download_history(db, page=page, page_size=page_size, status=status, search=search)


@router.get("/stream")
async def stream_downloads_data(request: Request):
    """SSE snapshots are explicitly typed so partial events cannot erase state."""
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            db = SessionLocal()
            try:
                yield f"event: snapshot\ndata: {json.dumps(get_download_snapshot(db))}\n\n"
            finally:
                db.close()
            await asyncio.sleep(2)
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/{job_id}")
def get_download_details(job_id: int, db: Session = Depends(get_db)):
    """Return one privacy-safe download details record."""
    job = db.get(DownloadJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Download not found.")
    return download_details(job)


@router.post("/{job_id}/cancel")
def cancel_download(job_id: int, db: Session = Depends(get_db)):
    """Cancel a queued or running download using the worker's existing flow."""
    job = db.get(DownloadJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Download not found.")
    if job.status not in (JobStatus.QUEUED.value, JobStatus.RUNNING.value):
        raise HTTPException(status_code=409, detail="Download is no longer active.")
    job.status = JobStatus.CANCELLED.value
    job.completed_at = datetime.now(UTC)
    db.commit()
    download_processes.cancel(job_id)
    return {"status": JobStatus.CANCELLED.value, "id": job.id}
