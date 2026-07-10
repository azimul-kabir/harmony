from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas.download import (
    DownloadJobResponse,
    DownloadRequest,
)
from app.api.schemas.queue import QueueResponse
from app.database.crud_downloads import (
    delete_job,
    get_job,
    list_jobs,
)
from app.database.session import get_db
from app.services.spotify.metadata import resolve_track
from app.exceptions.download import TrackAlreadyExistsError
from app.services.download_queue import enqueue_track

router = APIRouter(
    prefix="/api/downloads",
    tags=["downloads"],
)


@router.post(
    "",
    response_model=QueueResponse,
    status_code=201,
)
def queue_download(
    request: DownloadRequest,
    db: Session = Depends(get_db),
):
    track = resolve_track(  
        request.spotify_url,
    )

    try:
        return enqueue_track(
            db=db,
            track=track,
        )

    except TrackAlreadyExistsError:
        raise HTTPException(
            status_code=409,
            detail="Track already exists in library.",
        )


@router.get(
    "",
    response_model=list[DownloadJobResponse],
)
def downloads(
    db: Session = Depends(get_db),
):
    return list_jobs(db)


@router.get(
    "/{job_id}",
    response_model=DownloadJobResponse,
)
def download(
    job_id: int,
    db: Session = Depends(get_db),
):
    job = get_job(
        db=db,
        job_id=job_id,
    )

    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Download job not found.",
        )

    return job


@router.delete(
    "/{job_id}",
    status_code=204,
)
def remove_download(
    job_id: int,
    db: Session = Depends(get_db),
):
    job = get_job(
        db=db,
        job_id=job_id,
    )

    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Download job not found.",
        )

    delete_job(
        db=db,
        job=job,
    )