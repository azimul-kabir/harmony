from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import SyncSource


def create_sync_source(
    db: Session,
    *,
    type: str,
    spotify_id: str,
    spotify_url: str,
    name: str,
) -> SyncSource:
    sync = SyncSource(
        type=type,
        spotify_id=spotify_id,
        spotify_url=spotify_url,
        name=name,
    )

    db.add(sync)
    db.commit()
    db.refresh(sync)

    return sync


def get_sync_source(
    db: Session,
    sync_id: int,
) -> SyncSource | None:
    return db.get(
        SyncSource,
        sync_id,
    )


def get_sync_source_by_spotify_id(
    db: Session,
    spotify_id: str,
) -> SyncSource | None:
    return db.scalar(
        select(SyncSource).where(
            SyncSource.spotify_id == spotify_id
        )
    )


def list_sync_sources(
    db: Session,
) -> list[SyncSource]:
    return list(
        db.scalars(
            select(SyncSource).order_by(
                SyncSource.name
            )
        )
    )


def delete_sync_source(
    db: Session,
    sync: SyncSource,
) -> None:
    db.delete(sync)
    db.commit()