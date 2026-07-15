import asyncio
import json
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
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
            result = enqueue_track(
                db=db,
                track=track,
            )
            return {
                "status": result.status.value,
                "job_id": result.job_id,
            }
        except TrackAlreadyExistsError:
            return {
                "status": "owned",
            }

    if resource == "album":
        enqueue_album(
            db=db,
            spotify_url=request.url,
        )
        return {
            "status": "queued",
        }

    if resource == "playlist":
        summary = download_playlist(
            db=db,
            url=request.url,
        )
        return {
            "status": "queued",
            "summary": summary,
        }

    raise ValueError("Unsupported Spotify URL.")

@router.get("")
def list_downloads(db: Session = Depends(get_db)):
    jobs = (
        db.execute(
            select(DownloadJob).order_by(
                DownloadJob.id.desc()
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": job.id,
            "status": job.status,
            "title": job.title,
            "artist": job.artist,
            "spotify_url": job.spotify_url,
            "output_file": job.output_file,
            "error": job.error,
        }
        for job in jobs
    ]

@router.get("/stream")
async def stream_downloads_data(request: Request):
    """Server-Sent Events endpoint for real-time download history updates."""
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            
            db = SessionLocal()
            try:
                jobs = db.execute(
                    select(DownloadJob).order_by(DownloadJob.id.desc())
                ).scalars().all()
                
                payload = [
                    {
                        "id": job.id,
                        "status": job.status,
                        "title": job.title,
                        "artist": job.artist,
                        "album": job.album,
                    }
                    for job in jobs
                ]
                
                yield f"data: {json.dumps(payload)}\n\n"
            finally:
                db.close()
            
            await asyncio.sleep(2)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
