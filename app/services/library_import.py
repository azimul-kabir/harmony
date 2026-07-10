from pathlib import Path

from sqlalchemy.orm import Session

from app.database.crud import upsert_song
from app.services.metadata import read_metadata


def import_file(
    db: Session,
    path: str | Path,
) -> None:
    """
    Import an existing audio file into the Harmony database.

    Used by the library scanner.

    This function assumes the file is already inside the music library.
    """

    path = Path(path)

    metadata = read_metadata(path)

    if metadata is None:
        return

    metadata["path"] = str(path)
    metadata["filename"] = path.name

    upsert_song(
        db=db,
        metadata=metadata,
        commit=False,
    )

    db.commit()