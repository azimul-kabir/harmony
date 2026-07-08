from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas.download import (
    DownloadJobResponse,
    DownloadRequest,
)
from app.database.session import get_db
from app.services.download_queue import enqueue_track

from app.database.crud_downloads import list_jobs

router = APIRouter(
    prefix="/api/downloads",
    tags=["Downloads"],
)


@router.post("", response_model=DownloadJobResponse)
def queue_download(
    request: DownloadRequest,
    db: Session = Depends(get_db),
):
    from app.domain.track import Track

    track = Track(
        title=request.title,
        artist=request.artist,
        spotify_url=request.spotify_url,
    )

    return enqueue_track(db, track)


@router.get("")
def get_downloads(
    db: Session = Depends(get_db),
):
    return list_jobs(db)