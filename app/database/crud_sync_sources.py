from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import SyncSource


def get_all_sync_sources(
    db: Session,
):
    return (
        db.execute(
            select(SyncSource).order_by(SyncSource.name)
        )
        .scalars()
        .all()
    )


def create_sync_source(
    db: Session,
    *,
    type: str,
    spotify_id: str,
    spotify_url: str,
    name: str,
):
    source = SyncSource(
        type=type,
        spotify_id=spotify_id,
        spotify_url=spotify_url,
        name=name,
    )

    db.add(source)
    db.commit()
    db.refresh(source)

    return source


def get_sync_source_by_spotify_id(
    db: Session,
    spotify_id: str,
):
    return (
        db.execute(
            select(SyncSource).where(
                SyncSource.spotify_id == spotify_id
            )
        )
        .scalar_one_or_none()
    )