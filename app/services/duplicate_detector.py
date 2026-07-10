from pathlib import Path


def is_duplicate(destination: Path) -> bool:
    """
    Returns True if a file already exists at the destination.
    """

    return destination.exists()
