from sqlalchemy.orm import Session

from app.database.crud_sync_sources import list_sync_sources
from app.services.playlist_sync import sync_playlist


def sync_all_sources(
    db: Session,
) -> dict:
    tasks_created = 0

    for source in list_sync_sources(db):
        if not source.enabled:
            continue

        task = sync_playlist(
            db=db,
            source=source,
        )

        if task is not None:
            tasks_created += 1

    return {
        "sources": len(list_sync_sources(db)),
        "tasks_created": tasks_created,
    }