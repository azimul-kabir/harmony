from fastapi import APIRouter
from fastapi import HTTPException

from app.api.schemas.sync_source import (
    SyncSourceRequest,
    SyncSourceUpdateRequest,
)

from app.database.crud_sync_sources import (
    delete_sync_source,
    get_sync_source,
    list_sync_sources,
    update_sync_source_enabled,
)
from app.database.session import SessionLocal

from app.services.sync_sources import (
    create_playlist_source,
)

from app.services.playlist_sync import (
    sync_playlist,
)

router = APIRouter(
    prefix="/api/sources",
    tags=["sources"],
)


@router.get("")
def list_sources():
    db = SessionLocal()

    try:
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

    finally:
        db.close()


@router.post("", status_code=201)
def create_source(request: SyncSourceRequest):
    db = SessionLocal()

    try:
        source = create_playlist_source(
            db=db,
            spotify_url=request.spotify_url,
        )

        return {
            "id": source.id,
            "name": source.name,
            "type": source.type,
        }

    finally:
        db.close()


@router.post("/{source_id}/sync")
def sync_source(
    source_id: int,
):
    db = SessionLocal()

    try:
        source = get_sync_source(
            db=db,
            sync_id=source_id,
        )

        if source is None:
            raise HTTPException(
                status_code=404,
                detail="Source not found.",
            )

        task = sync_playlist(
            db=db,
            source=source,
        )

        if task is None:
            return {
                "message": "Nothing to sync.",
            }

        return {
            "task_id": task.id,
            "message": "Playlist sync started.",
        }

    finally:
        db.close()


@router.delete("/{source_id}")
def delete_source(
    source_id: int,
):
    db = SessionLocal()

    try:
        source = get_sync_source(
            db=db,
            sync_id=source_id,
        )

        if source is None:
            raise HTTPException(
                status_code=404,
                detail="Source not found.",
            )

        delete_sync_source(
            db=db,
            sync=source,
        )

        return {
            "message": "Source deleted.",
        }

    finally:
        db.close()


@router.patch("/{source_id}")
def update_source(
    source_id: int,
    request: SyncSourceUpdateRequest,
):
    db = SessionLocal()

    try:
        source = update_sync_source_enabled(
            db=db,
            sync_id=source_id,
            enabled=request.enabled,
        )

        if source is None:
            raise HTTPException(
                status_code=404,
                detail="Source not found.",
            )

        return {
            "id": source.id,
            "enabled": source.enabled,
        }

    finally:
        db.close()