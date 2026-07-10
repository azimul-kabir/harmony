from fastapi import APIRouter, HTTPException

from app.api.schemas.download import DownloadRequest
from app.database.session import SessionLocal
from app.domain.track import Track
from app.services.download_queue import enqueue_track
from app.services.spotify.metadata import resolve_track
from app.services.spotify.url import spotify_resource

router = APIRouter(
    prefix="/api/downloads",
    tags=["downloads"],
)


@router.post("", status_code=201)
def queue_download(request: DownloadRequest):
    db = SessionLocal()

    try:
        resource, _ = spotify_resource(request.url)

        if resource != "track":
            raise HTTPException(
                status_code=501,
                detail="Album and playlist downloads are not implemented yet.",
            )

        track: Track = resolve_track(request.url)

        enqueue_track(
            db=db,
            track=track,
        )

        return {
            "status": "queued",
        }

    finally:
        db.close()