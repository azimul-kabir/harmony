from fastapi import APIRouter
from sqlalchemy import select

from app.api.schemas.download import DownloadRequest
from app.database.models import DownloadJob
from app.database.session import SessionLocal
from app.services.download_queue import (
    enqueue_album,
    enqueue_track,
)
from app.services.playlist_download import download_playlist
from app.services.spotify.metadata import (
    resolve_track,
)
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

        if resource == "track":
            track = resolve_track(request.url)

            enqueue_track(
                db=db,
                track=track,
            )

            return {
                "status": "queued",
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

    finally:
        db.close()


@router.get("")
def list_downloads():
    db = SessionLocal()

    try:
        jobs = (
            db.execute(select(DownloadJob).order_by(DownloadJob.id.desc()))
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

    finally:
        db.close()
