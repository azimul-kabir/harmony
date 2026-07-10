from pathlib import Path

from sqlalchemy.orm import Session

from app.domain.track import Track
from app.services.import_engine import import_download


def import_downloaded_track(
    db: Session,
    downloaded_file: Path,
    track: Track,
) -> Path:
    """
    Public API for importing downloaded tracks.

    Future responsibilities:

    • duplicate detection
    • artwork handling
    • replaygain
    • lyrics
    • metadata enrichment
    """

    return import_download(
        db=db,
        downloaded_file=downloaded_file,
        spotify_track=track,
    )