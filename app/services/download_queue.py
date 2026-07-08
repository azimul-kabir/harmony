from sqlalchemy.orm import Session

from app.database.crud_downloads import create_job
from app.domain.track import Track


def enqueue_track(
    db: Session,
    track: Track,
):
    return create_job(
        db=db,
        spotify_url=track.spotify_url,
        title=track.title,
        artist=track.artist,
    )