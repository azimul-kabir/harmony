from pathlib import Path

from sqlalchemy.orm import Session

from app.database.crud import (
    UpsertStatus,
    upsert_song,
)
from app.services.metadata import read_metadata


def import_file(
    db: Session,
    path: str | Path,
) -> UpsertStatus | None:
    metadata = read_metadata(Path(path))

    if metadata is None:
        return None

    status, _ = upsert_song(
        db=db,
        metadata=metadata,
        commit=False,
    )

    return status