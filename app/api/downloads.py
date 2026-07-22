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
from app.domain.download import JobStatus
from app.services.download_dashboard import (
    TERMINAL_STATUSES, download_counts, download_details, download_history,
    get_download_snapshot,
)
from app.services.download_bulk import run_bulk_action

router = APIRouter(
    prefix="/api/downloads",
    tags=["downloads"],
)

@router.post("", status_code=201)
def queue_download(request: DownloadRequest, db: Session = Depends(get_db)):
    resource, _ = spotify_resource(request.url)

    if resource == "track":
        track = resolve_track(request.url)
        try:
            result = enqueue_track(db=db, track=track)
            return {"status": result.status.value, "job_id": result.job_id}
        except TrackAlreadyExistsError:
            return {"status": "owned"}

    if resource == "album":
        enqueue_album(db=db, spotify_url=request.url)
        return {"status": "queued"}

    if resource == "playlist":
        summary = download_playlist(db=db, url=request.url)
        return {"status": "queued", "summary": summary}

    raise ValueError("Unsupported Spotify URL.")

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
    return {"status": JobStatus.CANCELLED.value, "id": job.id}
