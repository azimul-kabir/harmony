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
from app.services.task_service import create_task, _finish_if_complete


def sync_playlist(
    db: Session,
    source: SyncSource,
) -> Task | None:
    """
    Synchronize a playlist source.

    Returns:
        Task:
            A download task representing the sync progress.
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

    queueable_tracks: list[Track] = []
    skipped_count = 0

    # Calculate exactly what needs downloading vs what is already owned
    for track in playlist.tracks:
        if _can_enqueue(
            db=db,
            track=track,
        ):
            queueable_tracks.append(track)
        else:
            skipped_count += 1

    logger.info(
        "{} of {} tracks need downloading. {} already owned/queued.",
        len(queueable_tracks),
        len(playlist.tracks),
        skipped_count,
    )

    # Set the task size to the ENTIRE playlist, not just the new songs
    task = create_task(
        db=db,
        name=playlist.name,
        spotify_url=source.spotify_url,
        source_id=source.id,
        task_type=TaskType.PLAYLIST_SYNC,
        total_items=len(playlist.tracks),
    )

    logger.info(
        "Created task #{}.",
        task.id,
    )

    # Instantly advance the progress bar for tracks we already have
    if skipped_count > 0:
        task.skipped_items = skipped_count
        db.commit()
        db.refresh(task)

    # Queue the new downloads
    for track in queueable_tracks:
        enqueue_track(
            db=db,
            track=track,
            task_id=task.id,
        )

    # If the playlist was already 100% synchronized, instantly complete the task
    # so the UI shows a "100 / 100" success state instead of doing nothing.
    if not queueable_tracks:
        _finish_if_complete(db=db, task=task)

    logger.info(
        "Queued {} download jobs.",
        len(queueable_tracks),
    )

    return task
