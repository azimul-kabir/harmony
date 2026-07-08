from sqlalchemy.orm import Session

from app.database.crud import find_song_by_title_artist

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
    song = find_song_by_title_artist(
        db=db,
        title=track.title,
        artist=track.artist,
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
        return existing_job

    #
    # Queue new job
    #
    return create_job(
        db=db,
        spotify_url=track.spotify_url,
        title=track.title,
        artist=track.artist,
    )