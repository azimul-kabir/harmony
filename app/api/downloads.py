from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.domain.track import Track

from app.exceptions.download import TrackAlreadyExistsError

from app.domain.download import JobStatus

from app.api.schemas.download import (
    DownloadJobResponse,
    DownloadRequest,
)
from app.database.session import get_db
from app.services.download_queue import enqueue_track

from app.database.crud_downloads import (
    get_job,
    list_jobs,
    delete_job,
)

router = APIRouter(
    prefix="/api/downloads",
    tags=["Downloads"],
)


@router.post("", response_model=DownloadJobResponse)
def queue_download(
    request: DownloadRequest,
    db: Session = Depends(get_db),
):
        track = Track(
        title=request.title,
        artist=request.artist,
        spotify_url=request.spotify_url,
    )

        try:
            return enqueue_track(db, track)

        except TrackAlreadyExistsError as ex:
            raise HTTPException(
                status_code=409,
                detail=str(ex),
            )


@router.get("", response_model=list[DownloadJobResponse])
def get_downloads(
    db: Session = Depends(get_db),
):
    return list_jobs(db)


@router.get("/{job_id}")
def get_download(
    job_id: int,
    db: Session = Depends(get_db),
):
    job = get_job(db, job_id)

    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found",
        )

    return job


@router.delete("/{job_id}", status_code=204)
def delete_download(
    job_id: int,
    db: Session = Depends(get_db),
):
    job = get_job(db, job_id)

    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found",
        )

    if job.status == JobStatus.RUNNING:
        raise HTTPException(
            status_code=409,
            detail="Job is currently running.",
        )

    delete_job(db, job)