from __future__ import annotations

from pathlib import Path
from typing import Any

from mutagen import File


def _first(value: Any, default=None):
    if value is None:
        return default

    if isinstance(value, list):
        return value[0] if value else default

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

    audio = File(path, easy=True)

    if audio is None:
        raise ValueError(f"Unsupported audio file: {path}")

    return {
        "path": str(path),
        "filename": path.name,
        "title": _first(audio.get("title")),
        "artist": _first(audio.get("artist")),
        "album_artist": _first(audio.get("albumartist")),
        "album": _first(audio.get("album")),
        "track": _parse_number(_first(audio.get("tracknumber"))),
        "disc": _parse_number(_first(audio.get("discnumber"))),
        "genre": _first(audio.get("genre")),
        "year": _parse_number(_first(audio.get("date"))),
        "duration": round(audio.info.length, 2) if audio.info else None,
        "file_size": path.stat().st_size,
        "modified_time": int(path.stat().st_mtime),
    }