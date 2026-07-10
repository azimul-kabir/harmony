from pathlib import Path

from sqlalchemy.orm import Session


def is_duplicate(
    db: Session,
    file: Path,
) -> bool:
    """
    Placeholder duplicate detector.

    Future implementation will compare:
    - Spotify ID
    - ISRC
    - Metadata
    """

    return False