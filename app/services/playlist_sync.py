from sqlalchemy.orm import Session
from datetime import UTC, datetime

from app.core.logging import logger
from app.core.config import get_settings
from app.database.models import SyncSource, Task
from app.domain.task import TaskType
from app.domain.track import Track
from app.services.download_queue import _can_enqueue, enqueue_track
from app.services.playlist import import_playlist
from app.services.playlist_manager import sync_database_playlist, export_m3u
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
        # 2. Run the heavy SpotDL process
        domain_playlist = import_playlist(source.spotify_url)
        
        # 3. Update the names now that we have real data
        if source.name == "Fetching Playlist Data...":
            source.name = domain_playlist.name
            
        task.name = domain_playlist.name
        task.total_items = len(domain_playlist.tracks)
        
        db.commit()
        db.refresh(source)
        db.refresh(task)
        
        logger.info("Playlist '{}' contains {} tracks.", domain_playlist.name, len(domain_playlist.tracks))
        
        # 4. Update the Playlist Database with the latest Spotify structure
        set_current_item(db=db, task=task, item="Saving playlist structure…")
        db_playlist = sync_database_playlist(db, source, domain_playlist)
        source.last_synced_at = datetime.now(UTC)
        db.commit()
        db.refresh(source)
        
        # 5. Export M3U immediately, passing the freshly scraped domains tracks to fix historic library duplicates
        set_current_item(db=db, task=task, item="Creating the initial M3U playlist…")
        export_m3u(db, db_playlist, domain_tracks=domain_playlist.tracks)

        if not domain_playlist.tracks:
            logger.warning("Playlist '{}' is empty.", domain_playlist.name)
            _finish_if_complete(db=db, task=task)
            navidrome_playlist_reimport.schedule(task.id)
            return task
            
        # 6. Check duplicates and queue missing tracks
        queueable_tracks: list[tuple[int, Track]] = []
        skipped_count = 0
        set_current_item(db=db, task=task, item="Checking which tracks are already owned…")
        
        for position, track in enumerate(domain_playlist.tracks, 1):
            if _can_enqueue(db=db, track=track):
                queueable_tracks.append((position, track))
            else:
                skipped_count += 1
                
        if skipped_count > 0:
            task.skipped_items = skipped_count
            db.commit()
            db.refresh(task)
            
        set_current_item(
            db=db,
            task=task,
            item=f"Queueing 0 of {len(queueable_tracks)} missing tracks…",
        )
        
        for queued_index, (position, track) in enumerate(queueable_tracks, 1):
            enqueue_track(
                db=db,
                track=track,
                task_id=task.id,
                queue_position=position,
            )
            if queued_index % 25 == 0 or queued_index == len(queueable_tracks):
                set_current_item(
                    db=db,
                    task=task,
                    item=(
                        f"Queueing {queued_index} of "
                        f"{len(queueable_tracks)} missing tracks…"
                    ),
                )
            
        if not queueable_tracks:
            _finish_if_complete(db=db, task=task)
            navidrome_playlist_reimport.schedule(task.id)
        else:
            set_current_item(
                db=db,
                task=task,
                item=(
                    f"{len(queueable_tracks)} downloads queued; "
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
