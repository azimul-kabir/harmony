import asyncio
import json
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.api.schemas.download import DownloadRequest
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
from app.services.download_dashboard import TERMINAL_STATUSES, get_download_snapshot

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

# Inside app/api/downloads.py, update the stream_downloads_data function payload:

@router.get("/stream")
async def stream_downloads_data(request: Request):
    """Server-Sent Events endpoint for real-time download history updates."""
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
                        
            db = SessionLocal()
            try:
                payload = get_download_snapshot(db)
                                
                yield f"data: {json.dumps(payload)}\n\n"
            finally:
                db.close()
                        
            await asyncio.sleep(2)
    return StreamingResponse(event_generator(), media_type="text/event-stream")
