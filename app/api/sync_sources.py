import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas.sync_source import (
    SyncSourceRequest,
    SyncSourceUpdateRequest,
)
from app.database.crud_sync_sources import (
    delete_sync_source,
    get_sync_source,
    list_sync_sources,
    update_sync_source_enabled,
    create_sync_source,
    get_sync_source_by_spotify_id,
)
from app.database.models import Playlist, Task
from app.database.session import get_db, SessionLocal
from app.services.playlist_sync import sync_playlist
from app.services.playlist_manager import count_m3u_entries, playlist_file_path
from app.services.spotify.url import spotify_resource

router = APIRouter(
    prefix="/api/sources",
    tags=["sources"],
)

def run_background_sync(source_id: int):
    db = SessionLocal()
    try:
        source = get_sync_source(db=db, sync_id=source_id)
        if source:
            sync_playlist(db=db, source=source)
    finally:
        db.close()

def create_playlist_source(db: Session, spotify_url: str):
    resource, spotify_id = spotify_resource(spotify_url)
    
    if resource != "playlist":
        raise ValueError("Only Spotify playlists are supported.")

    existing = get_sync_source_by_spotify_id(db, spotify_id)
    if existing:
        return existing

    return create_sync_source(
        db=db,
        type="playlist",
        spotify_id=spotify_id,
        spotify_url=spotify_url,
        name="Fetching Playlist Data...",
    )

@router.get("")
def list_sources(db: Session = Depends(get_db)):
    sources = list_sync_sources(db)
    return [
        {
            "id": source.id,
            "type": source.type,
            "name": source.name,
            "spotify_url": source.spotify_url,
            "enabled": source.enabled,
            "last_synced_at": source.last_synced_at,
        }
        for source in sources
    ]

@router.post("", status_code=201)
def create_source(request: SyncSourceRequest, db: Session = Depends(get_db)):
    source = create_playlist_source(
        db=db,
        spotify_url=request.spotify_url,
    )
    return {
        "id": source.id,
        "name": source.name,
        "type": source.type,
    }

@router.post("/{source_id}/sync")
def sync_source(source_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    source = get_sync_source(
        db=db,
        sync_id=source_id,
    )
    if source is None:
        raise HTTPException(
            status_code=404,
            detail="Source not found.",
        )
    
    # Hand the heavy lifting off to the background instantly
    background_tasks.add_task(run_background_sync, source.id)
    
    return {
        "message": "Playlist sync started in the background.",
    }

@router.delete("/{source_id}")
def delete_source(source_id: int, db: Session = Depends(get_db)):
    source = get_sync_source(db=db, sync_id=source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found.")
    delete_sync_source(db=db, sync=source)
    return {"message": "Source deleted."}

@router.patch("/{source_id}")
def update_source(source_id: int, request: SyncSourceUpdateRequest, db: Session = Depends(get_db)):
    source = update_sync_source_enabled(db=db, sync_id=source_id, enabled=request.enabled)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found.")
    return {"id": source.id, "enabled": source.enabled}

@router.get("/stream")
async def stream_sources_data(request: Request):
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            
            db = SessionLocal()
            try:
                sources = list_sync_sources(db)
                payload = []
                
                for source in sources:
                    playlist = db.scalar(
                        select(Playlist).where(
                            Playlist.spotify_id == source.spotify_id
                        )
                    )
                    latest_task = db.execute(
                        select(Task)
                        .where(Task.source_id == source.id)
                        .order_by(Task.created_at.desc())
                        .limit(1)
                    ).scalar_one_or_none()
                    
                    task_data = None
                    if latest_task:
                        task_data = {
                            "id": latest_task.id,
                            "status": latest_task.status,
                            "total": latest_task.total_items,
                            "completed": latest_task.completed_items,
                            "failed": latest_task.failed_items,
                            "skipped": latest_task.skipped_items,
                            "current": latest_task.current_item,
                        }
                    
                    payload.append({
                        "id": source.id,
                        "type": source.type,
                        "name": source.name,
                        "spotify_url": source.spotify_url,
                        "enabled": source.enabled,
                        "last_synced_at": source.last_synced_at.isoformat() if source.last_synced_at else None,
                        "playlist": {
                            "id": playlist.id,
                            "total": playlist.track_count,
                            "exported": count_m3u_entries(
                                playlist_file_path(playlist.name)
                            ),
                        } if playlist else None,
                        "task": task_data
                    })
                
                yield f"data: {json.dumps(payload)}\n\n"
            finally:
                db.close()
            
            await asyncio.sleep(2)
    return StreamingResponse(event_generator(), media_type="text/event-stream")
