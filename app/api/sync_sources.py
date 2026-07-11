from fastapi import APIRouter

from app.api.schemas.sync_source import SyncSourceRequest

from app.database.crud_sync_sources import (
    get_all_sync_sources,
)
from app.database.session import SessionLocal

from app.services.sync_sources import (
    create_playlist_source,
)

router = APIRouter(
    prefix="/api/sources",
    tags=["sources"],
)


@router.get("")
def list_sources():
    db = SessionLocal()

    try:
        sources = get_all_sync_sources(db)

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