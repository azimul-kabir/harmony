from __future__ import annotations

from pathlib import Path
from typing import Any

from mutagen import File


def _first(value: Any, default=None):
    if value is None:
        return default

    if isinstance(value, list):
        return value[0] if value else default

    if hasattr(value, "text"):
        return value.text[0] if value.text else default

    return value


def _parse_number(value):
    if value is None:
        return None

    value = str(value)

    if "/" in value:
        value = value.split("/")[0]

    try:
        return int(value)
    except ValueError:
        return None


def read_metadata(file_path: str | Path) -> dict:
    path = Path(file_path)

    audio = File(path, easy=False)
    easy = File(path, easy=True)

    if audio is None or easy is None:
        raise ValueError(f"Unsupported audio file: {path}")

    tags = audio.tags or {}

    return {
        "path": str(path),
        "filename": path.name,
        # Basic
        "title": _first(easy.get("title")),
        "artist": _first(easy.get("artist")),
        "album_artist": _first(easy.get("albumartist")),
        "album": _first(easy.get("album")),
        # Track
        "track": _parse_number(_first(easy.get("tracknumber"))),
        "disc": _parse_number(_first(easy.get("discnumber"))),
        # Other
        "genre": _first(easy.get("genre")),
        "year": _parse_number(_first(easy.get("date"))),
        # File
        "duration": round(audio.info.length, 2) if audio.info else None,
        "file_size": path.stat().st_size,
        "modified_time": int(path.stat().st_mtime),
        # External IDs
        "spotify_track_id": _first(tags.get("spotify_track_id")),
        "spotify_album_id": _first(tags.get("spotify_album_id")),
        "isrc": _first(tags.get("isrc")),
    }
