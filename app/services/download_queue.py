from sqlalchemy.orm import Session

from app.domain.queue import QueueResult, QueueStatus

from app.database.crud import find_song

from app.exceptions.download import (
    TrackAlreadyExistsError,
)

from app.database.crud_downloads import (
    create_job,
    find_active_job_by_spotify_url,
)

from app.domain.track import Track


def enqueue_track(
    db: Session,
    track: Track,
):
    if track.spotify_url is None:
        raise ValueError("Spotify URL is required.")

    #
    # Already in library?
    #
    song = find_song(
        db=db,
        title=track.title,
        artist=track.artist,
        album=track.album,
    )

    if song is not None:
        raise TrackAlreadyExistsError(
            "Track already exists in library."
        )

    #
    # Already downloading?
    #
    existing_job = find_active_job_by_spotify_url(
        db=db,
        spotify_url=track.spotify_url,
    )

    if existing_job is not None:
        return QueueResult(
            job_id=existing_job.id,
            status=QueueStatus.ALREADY_QUEUED,
        )

    #
    # Queue new job
    #
    job = create_job(
        db=db,
        track=track
    )

    return QueueResult(
        job_id=job.id,
        status=QueueStatus.CREATED,
    )