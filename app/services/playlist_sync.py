from sqlalchemy.orm import Session
from datetime import UTC, datetime

from app.core.logging import logger
from app.core.config import get_settings
from app.database.models import SyncSource, Task
from app.domain.task import TaskStatus, TaskType
from app.domain.track import Track
from app.services.download_queue import _can_enqueue, enqueue_tracks_bulk
from app.services.playlist_manager import (
    append_incremental_playlist_batch,
    begin_incremental_playlist,
    export_m3u,
)
from app.services.spotify.playlist_batches import UnofficialSpotifyPlaylistReader
from app.services.task_service import (
    create_task,
    _finish_if_complete,
    start_task,
    set_current_item,
    _fail_task,
)
from app.services.navidrome_playlist_sync import navidrome_playlist_reimport

def sync_playlist(
    db: Session,
    source: SyncSource,
) -> Task | None:
    logger.info("Starting sync for playlist '{}'", source.name)
    
    # 1. Create the task IMMEDIATELY so the UI sees it.
    task = create_task(
        db=db,
        name=f"Syncing {source.name}",
        spotify_url=source.spotify_url,
        source_id=source.id,
        task_type=TaskType.PLAYLIST_SYNC,
        total_items=0,
    )
    start_task(db=db, task=task)
    timeout_minutes = max(
        1,
        round(get_settings().spotify_playlist_metadata_timeout_seconds / 60),
    )
    set_current_item(
        db=db,
        task=task,
        item=f"Fetching Spotify playlist metadata (timeout: {timeout_minutes} minutes)…",
    )
    
    try:
        # Read the public playlist incrementally through SpotDL's unofficial
        # provider so downloads can begin after the first 50 tracks.
        reader = UnofficialSpotifyPlaylistReader(source.spotify_url)
        metadata = reader.metadata()

        if source.name == "Fetching Playlist Data...":
            source.name = metadata.name
        task.name = metadata.name
        db.commit()
        db.refresh(source)
        db.refresh(task)
        db_playlist = begin_incremental_playlist(db, source, metadata.name)
        discovered_count = 0
        queued_count = 0
        skipped_count = 0
        all_tracks: list[Track] = []
        seen_queue_urls: set[str] = set()

        for batch_number, batch in enumerate(reader.batches(), 1):
            batch_start = discovered_count
            discovered_count += len(batch)
            all_tracks.extend(batch)
            # Reserve one discovery unit so very fast workers cannot complete
            # the task while later provider pages are still being fetched.
            task.total_items = discovered_count + 1
            set_current_item(
                db=db,
                task=task,
                item=f"Saving batch {batch_number}: {discovered_count} tracks discovered…",
            )
            append_incremental_playlist_batch(db, db_playlist, batch, batch_start)

            queueable_tracks: list[tuple[int, Track]] = []
            for offset, track in enumerate(batch, batch_start + 1):
                source_url = track.source_url or track.spotify_url
                if (
                    source_url
                    and source_url not in seen_queue_urls
                    and _can_enqueue(db=db, track=track)
                ):
                    queueable_tracks.append((offset, track))
                    seen_queue_urls.add(source_url)
                else:
                    skipped_count += 1
            task.skipped_items = skipped_count
            db.commit()

            if queueable_tracks:
                enqueue_tracks_bulk(db, queueable_tracks, task.id)
                queued_count += len(queueable_tracks)
            set_current_item(
                db=db,
                task=task,
                item=(f"Batch {batch_number} saved; {discovered_count} discovered, "
                      f"{queued_count} downloads queued…"),
            )

        if not all_tracks:
            raise RuntimeError("Playlist is empty.")

        source.last_synced_at = datetime.now(UTC)
        db_playlist.last_synced_at = source.last_synced_at
        task.total_items = discovered_count
        db.commit()
        set_current_item(db=db, task=task, item="Creating the final M3U playlist…")
        export_m3u(db, db_playlist, domain_tracks=all_tracks)

        logger.info("Playlist '{}' contains {} tracks.", metadata.name, discovered_count)
        _finish_if_complete(db=db, task=task)
        if task.status in {TaskStatus.COMPLETED.value, TaskStatus.FAILED.value}:
            navidrome_playlist_reimport.schedule(task.id)
        else:
            set_current_item(
                db=db,
                task=task,
                item=(
                    f"{queued_count} downloads queued; "
                    "waiting for workers…"
                ),
            )
            
        return task
        
    except Exception as error:
        logger.exception("Failed to sync playlist")
        detail = str(error)
        if "timed out after" in detail:
            task.error_code = "playlist_metadata_timeout"
            task.error_summary = (
                "Spotify playlist metadata retrieval timed out. Increase the "
                "Spotify playlist metadata timeout in Settings → Downloads "
                "and try again."
            )
        elif "SpotDL is unavailable" in detail:
            task.error_code = "spotdl_unavailable"
            task.error_summary = detail
        else:
            task.error_code = "playlist_metadata_failed"
            task.error_summary = (
                "Harmony could not retrieve this playlist's metadata. Check "
                "that the playlist is accessible and try again."
            )
        db.commit()
        _fail_task(db=db, task=task)
        return task
