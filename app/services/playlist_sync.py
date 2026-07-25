from sqlalchemy.orm import Session
from datetime import UTC, datetime

from app.core.logging import logger
from app.core.config import get_settings
from app.database.models import SyncSource, Task
from app.domain.task import TaskType
from app.domain.track import Track
from app.services.download_queue import _can_enqueue, enqueue_track, bulk_enqueue_tracks
from app.services.spotify.playlist_batches import playlist_batches
from app.services.playlist_manager import begin_playlist_refresh, append_playlist_batch, complete_playlist_refresh
from app.database.crud_sync_sources import get_sync_source_by_spotify_id
from app.database.models import PlaylistImportBatch, Playlist
from sqlalchemy import select
from app.services.playlist import import_playlist
from app.services.playlist_manager import sync_database_playlist, export_m3u, save_database_playlist
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
        item=f"Fetching Spotify metadata (timeout: {timeout_minutes} minutes)…",
    )
    
    try:
        # Resolve the db playlist so we can write to it progressively
        db_playlist = db.execute(
            select(Playlist).where(Playlist.spotify_id == source.spotify_id)
        ).scalar_one_or_none()
        
        if not db_playlist:
            # We need to bootstrap a mostly empty playlist just to have the ID
            from app.domain.playlist import Playlist as DomainPlaylist
            temp_dp = DomainPlaylist(name=source.name, url=source.spotify_url, tracks=[])
            db_playlist = save_database_playlist(db, source.spotify_id, temp_dp)
            
        begin_playlist_refresh(db, db_playlist)
        
        discovered_count = 0
        queued_count = 0
        skipped_count = 0
        
        # 2. Consume the generator
        for batch_number, tracks in enumerate(playlist_batches(source.spotify_url), 1):


            if source.name == "Fetching Playlist Data..." and batch_number == 1:
                try:
                    from spotapi import PublicPlaylist
                    playlist_id = source.spotify_url.split("playlist/")[-1].split("?")[0]
                    info = PublicPlaylist(playlist_id).get_playlist_info(limit=1)
                    real_name = info.get("data", {}).get("playlistV2", {}).get("name")
                    if real_name:
                        source.name = real_name
                        db_playlist.name = real_name
                        task.name = real_name
                        db.commit()
                except Exception as e:
                    logger.warning(f"Could not fetch real playlist name: {e}")


            # Persist batch durable state
            batch_record = PlaylistImportBatch(
                task_id=task.id,
                playlist_id=db_playlist.id,
                batch_number=batch_number,
                start_position=discovered_count,
                end_position=discovered_count + len(tracks),
                discovered_count=len(tracks),
            )
            db.add(batch_record)

            # Save playlist structure chunk
            append_playlist_batch(
                db=db,
                playlist_id=db_playlist.id,
                tracks=tracks,
                start_position=discovered_count,
            )

            # Check duplicates and queue missing tracks for this chunk
            set_current_item(
                db=db,
                task=task,
                item=f"Batch {batch_number}: Checking your library for {len(tracks)} tracks…"
            )

            queueable_tracks = []
            for idx, track in enumerate(tracks):
                queue_position = discovered_count + idx + 1
                if _can_enqueue(db=db, track=track):
                    queueable_tracks.append((queue_position, track))
                else:
                    skipped_count += 1

            batch_record.skipped_count = skipped_count

            set_current_item(
                db=db,
                task=task,
                item=f"Batch {batch_number}: Creating {len(queueable_tracks)} download jobs…"
            )

            results = bulk_enqueue_tracks(
                db=db,
                tracks_with_positions=queueable_tracks,
                task_id=task.id,
            )

            queued_count += len(results)
            discovered_count += len(tracks)
            batch_record.queued_count = len(results)
            batch_record.status = "completed"
            batch_record.completed_at = datetime.now(UTC)

            # Progressively update task stats
            task.total_items = discovered_count
            task.skipped_items = skipped_count
            db.commit()

        # Completion
        complete_playlist_refresh(db, db_playlist)
        db_playlist.last_synced_at = datetime.now(UTC)
        source.last_synced_at = datetime.now(UTC)
        db.commit()
        
        # We need the full tracks for the M3U export
        domain_tracks = [] # We just pass none, the manager will lookup by ID
        set_current_item(db=db, task=task, item="Creating M3U…")
        export_m3u(db, db_playlist)

        if discovered_count == 0:
            logger.warning("Playlist '{}' is empty.", source.name)
            _finish_if_complete(db=db, task=task)
            navidrome_playlist_reimport.schedule(task.id)
            return task
            
        if queued_count == 0:
            _finish_if_complete(db=db, task=task)
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
