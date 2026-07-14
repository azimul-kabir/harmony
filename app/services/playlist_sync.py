from sqlalchemy.orm import Session

from app.core.logging import logger
from app.database.models import SyncSource, Task
from app.domain.task import TaskType
from app.domain.track import Track
from app.services.download_queue import (
    _can_enqueue,
    enqueue_track,
)
from app.services.playlist import import_playlist
from app.services.task_service import create_task


def sync_playlist(
    db: Session,
    source: SyncSource,
) -> Task | None:
    """
    Synchronize a playlist source.

    Returns:
        Task:
            A download task if new tracks were queued.

        None:
            If the playlist is already fully synchronized.
    """

    logger.info(
        "Starting sync for playlist '{}'",
        source.name,
    )

    playlist = import_playlist(
        source.spotify_url,
    )

    logger.info(
        "Playlist '{}' contains {} tracks.",
        playlist.name,
        len(playlist.tracks),
    )

    if not playlist.tracks:
        logger.warning(
            "Playlist '{}' is empty.",
            playlist.name,
        )
        return None

    queueable_tracks: list[Track] = [
        track
        for track in playlist.tracks
        if _can_enqueue(
            db=db,
            track=track,
        )
    ]

    logger.info(
        "{} of {} tracks need downloading.",
        len(queueable_tracks),
        len(playlist.tracks),
    )

    if not queueable_tracks:
        logger.info(
            "Playlist '{}' is already synchronized.",
            playlist.name,
        )
        return None

    task = create_task(
        db=db,
        name=playlist.name,
        spotify_url=source.spotify_url,
        source_id=source.id,
        task_type=TaskType.PLAYLIST_SYNC,
        total_items=len(queueable_tracks),
    )

    logger.info(
        "Created task #{}.",
        task.id,
    )

    for track in queueable_tracks:
        enqueue_track(
            db=db,
            track=track,
            task_id=task.id,
        )

    logger.info(
        "Queued {} download jobs.",
        len(queueable_tracks),
    )

    return task