from sqlalchemy.orm import Session

from app.services.task_service import create_task
from app.domain.task import TaskType
from app.database.crud import find_song
from app.database.crud_downloads import (
    create_job,
    find_active_job_by_spotify_url,
)
from app.domain.queue import QueueResult, QueueStatus
from app.domain.track import Track
from app.exceptions.download import TrackAlreadyExistsError
from app.services.duplicate_detector import is_duplicate
from app.services.library_paths import build_destination
from app.services.playlist import import_playlist
from app.services.spotify.metadata import resolve_album


def enqueue_track(
    db: Session,
    track: Track,
    task_id: int | None = None,
) -> QueueResult:

    if not _can_enqueue(
        db=db,
        track=track,
    ):
        raise TrackAlreadyExistsError(
            "Track already exists or is already queued."
        )

    spotify_url = track.spotify_url
    assert spotify_url is not None

    if task_id is None:
        task = create_task(
            db=db,
            name=track.title or "Unknown Track",
            spotify_url=spotify_url,
            task_type=TaskType.TRACK_DOWNLOAD,
            total_items=1,
        )

        task_id = task.id

    job = create_job(
        db=db,
        track=track,
        task_id=task_id,
    )

    return QueueResult(
        job_id=job.id,
        status=QueueStatus.CREATED,
    )


def enqueue_album(
    db: Session,
    spotify_url: str,
) -> list[QueueResult]:
    tracks = resolve_album(spotify_url)

    queue: list[Track] = []

    for track in tracks:
        if _can_enqueue(
            db=db,
            track=track,
        ):
            queue.append(track)

    if not queue:
        return []

    task = create_task(
        db=db,
        name=queue[0].album or "Unknown Album",
        spotify_url=spotify_url,
        task_type=TaskType.ALBUM_DOWNLOAD,
        total_items=len(queue),
    )

    results: list[QueueResult] = []

    for track in queue:
        results.append(
            enqueue_track(
                db=db,
                track=track,
                task_id=task.id,
            )
        )

    return results


def enqueue_playlist(
    db: Session,
    spotify_url: str,
) -> list[QueueResult]:
    playlist = import_playlist(spotify_url)

    queue: list[Track] = []

    for track in playlist.tracks:
        if _can_enqueue(
            db=db,
            track=track,
        ):
            queue.append(track)

    if not queue:
        return []

    task = create_task(
        db=db,
        name=playlist.name,
        spotify_url=spotify_url,
        task_type=TaskType.PLAYLIST_DOWNLOAD,
        total_items=len(queue),
    )

    results: list[QueueResult] = []

    for track in queue:
        results.append(
            enqueue_track(
                db=db,
                track=track,
                task_id=task.id,
            )
        )

    return results


def _track_destination_exists(track: Track) -> bool:
    metadata = {
        "path": f"{track.title or track.spotify_track_id or 'download'}.mp3",
        "title": track.title,
        "artist": track.artist,
        "album_artist": track.album_artist,
        "album": track.album,
        "track": track.track,
    }

    return is_duplicate(build_destination(metadata))


def _can_enqueue(
    db: Session,
    track: Track,
) -> bool:
    song = find_song(
        db=db,
        title=track.title,
        artist=track.artist,
        album=track.album,
        spotify_track_id=track.spotify_track_id,
        isrc=track.isrc,
    )

    if track.spotify_url is None:
        return False

    if song is not None:
        return False

    if _track_destination_exists(track):
        return False

    existing_job = find_active_job_by_spotify_url(
        db=db,
        spotify_url=track.spotify_url,
    )

    if existing_job is not None:
        return False

    return True