from sqlalchemy.orm import Session

from app.database.crud import find_song
from app.database.crud_downloads import (
    create_job,
    find_active_job_by_spotify_url,
)
from app.domain.queue import QueueResult, QueueStatus
from app.domain.track import Track
from app.exceptions.download import TrackAlreadyExistsError
from app.services.spotify.metadata import (
    resolve_album,
    resolve_playlist,
)


def enqueue_track(
    db: Session,
    track: Track,
) -> QueueResult:
    if track.spotify_url is None:
        raise ValueError("Spotify URL is required.")

    song = find_song(
        db=db,
        title=track.title or "",
        artist=track.artist or "",
        album=track.album,
    )

    if song is not None:
        raise TrackAlreadyExistsError("Track already exists in library.")

    existing_job = find_active_job_by_spotify_url(
        db=db,
        spotify_url=track.spotify_url,
    )

    if existing_job is not None:
        return QueueResult(
            job_id=existing_job.id,
            status=QueueStatus.ALREADY_QUEUED,
        )

    job = create_job(
        db=db,
        track=track,
    )

    return QueueResult(
        job_id=job.id,
        status=QueueStatus.CREATED,
    )


def enqueue_album(
    db: Session,
    spotify_url: str,
) -> list[QueueResult]:
    results: list[QueueResult] = []

    for track in resolve_album(spotify_url):
        try:
            results.append(
                enqueue_track(
                    db=db,
                    track=track,
                )
            )
        except TrackAlreadyExistsError:
            pass

    return results


def enqueue_playlist(
    db: Session,
    spotify_url: str,
) -> list[QueueResult]:
    results: list[QueueResult] = []

    for track in resolve_playlist(spotify_url):
        try:
            results.append(
                enqueue_track(
                    db=db,
                    track=track,
                )
            )
        except TrackAlreadyExistsError:
            pass

    return results
