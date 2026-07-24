from pathlib import Path

from sqlalchemy.orm import Session

from app.services.import_engine import import_download
def import_downloaded_track(
    db: Session,
    downloaded_file: Path,
    cover_url: str | None = None,  # <-- NEW: Accept the cover URL
    genre_provenance: str | None = None,
    download_source: str = "spotdl",
) -> Path:
    destination = import_download(
        db=db,
        downloaded_file=downloaded_file,
        download_source=download_source,
        cover_url=cover_url,
        genre_provenance=genre_provenance,
    )

    return destination
