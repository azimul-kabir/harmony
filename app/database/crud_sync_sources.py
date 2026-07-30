from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import SyncSource


def create_sync_source(
    db: Session,
    *,
    type: str,
    spotify_id: str | None = None,
    spotify_url: str | None = None,
    provider: str = "spotify",
    external_id: str | None = None,
    source_url: str | None = None,
    name: str,
) -> SyncSource:
    source = SyncSource(
        type=type,
        provider=provider,
        external_id=external_id or spotify_id,
        source_url=source_url or spotify_url,
        # Keep the legacy columns populated during the compatibility window.
        spotify_id=spotify_id or external_id,
        spotify_url=spotify_url or source_url,
        name=name,
    )

    db.add(source)
    db.commit()
    db.refresh(source)

    return source


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


def get_sync_source_by_identity(db: Session, provider: str, external_id: str) -> SyncSource | None:
    return db.scalar(select(SyncSource).where(
        SyncSource.provider == provider,
        SyncSource.external_id == external_id,
    )) or (get_sync_source_by_spotify_id(db, external_id) if provider == "spotify" else None)


def list_sync_sources(
    db: Session,
) -> list[SyncSource]:
    return list(
        db.scalars(
            select(SyncSource).order_by(
                SyncSource.name,
            )
        )
    )


def delete_sync_source(
    db: Session,
    sync: SyncSource,
) -> None:
    db.delete(sync)
    db.commit()


def update_sync_source_enabled(
    db: Session,
    sync_id: int,
    enabled: bool,
) -> SyncSource | None:
    source = get_sync_source(
        db=db,
        sync_id=sync_id,
    )

    if source is None:
        return None

    source.enabled = enabled

    db.commit()
    db.refresh(source)

    return source
