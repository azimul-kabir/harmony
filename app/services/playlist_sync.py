from sqlalchemy.orm import Session

from app.database.models import SyncSource, Task
from app.services.playlist import import_playlist
from app.services.download_queue import _can_enqueue
from app.domain.track import Track
from app.domain.task import TaskType
from app.services.task_service import create_task
from app.services.download_queue import enqueue_track


def sync_playlist(
    db: Session,
    source: SyncSource,
) -> Task | None:
    """
    Synchronize a single playlist source.

    Returns:
        Task:
            A download task if new tracks were queued.

        None:
            If the playlist is already fully synchronized.
    """

    playlist = import_playlist(
        source.spotify_url,
    )

    if not playlist.tracks:
        return None
    
    queueable_tracks: list[Track] = [
        track
        for track in playlist.tracks
        if _can_enqueue(
            db=db,
            track=track,
        )
    ]

    if not queueable_tracks:
        return None
    
    task = create_task(
        db=db,
        name=playlist.name,
        spotify_url=source.spotify_url,
        source_id=source.id,
        task_type=TaskType.PLAYLIST_SYNC,
        total_items=len(queueable_tracks),
    )

    for track in queueable_tracks:
        enqueue_track(
            db=db,
            track=track,
            task_id=task.id,
        )

    return task