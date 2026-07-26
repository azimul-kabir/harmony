from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib
import json

from mutagen import File
from app.services.lyrics import extract_lyrics


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


def _parse_total(value):
    if value is None:
        return None
    parts = str(value).split("/", 1)
    if len(parts) != 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def _parse_bool(value):
    normalized = str(value).strip().casefold() if value is not None else ""
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    return None


def _tag_value(tags: Any, *names: str):
    """Read a known external-ID tag across Vorbis/MP4 and ID3 TXXX forms."""
    for name in names:
        value = tags.get(name) if hasattr(tags, "get") else None
        if value is not None:
            return _first(value)
    # ID3 stores the user-visible names written by file_tag_writer as TXXX
    # frames.  This is indexing/repair logic, not artwork-fetch lookup.
    if getattr(tags, "getall", None):
        requested = {name.casefold() for name in names}
        for frame in tags.getall("TXXX"):
            if str(getattr(frame, "desc", "")).casefold() in requested:
                return _first(getattr(frame, "text", None))
    return None


def read_metadata(file_path: str | Path) -> dict:
    path = Path(file_path)

    audio = File(path, easy=False)
    easy = File(path, easy=True)

    if audio is None or easy is None:
        raise ValueError(f"Unsupported audio file: {path}")

    tags = audio.tags or {}

    info = audio.info
    codec = path.suffix.lower().lstrip(".") or audio.__class__.__name__.lower()
    bitrate = getattr(info, "bitrate", None) if info else None
    sample_rate = getattr(info, "sample_rate", None) if info else None

    metadata = {
        "path": str(path),
        "filename": path.name,
        # Basic
        "title": _first(easy.get("title")),
        "artist": _first(easy.get("artist")),
        "album_artist": _first(easy.get("albumartist")),
        "album": _first(easy.get("album")),
        # Track
        "track": _parse_number(_first(easy.get("tracknumber"))),
        "track_total": _parse_total(_first(easy.get("tracknumber"))),
        "disc": _parse_number(_first(easy.get("discnumber"))),
        "disc_total": _parse_total(_first(easy.get("discnumber"))),
        # Other
        "genre": _first(easy.get("genre")),
        "year": _parse_number(_first(easy.get("date"))),
        # File
        "duration": round(info.length, 2) if info else None,
        "bitrate": int(bitrate) if bitrate else None,
        "codec": codec,
        "sample_rate": int(sample_rate) if sample_rate else None,
        "file_size": path.stat().st_size,
        "modified_time": int(path.stat().st_mtime),
        # External IDs
        "spotify_track_id": _first(tags.get("spotify_track_id")),
        "spotify_album_id": _first(tags.get("spotify_album_id")),
        "musicbrainz_recording_id": _tag_value(
            tags, "musicbrainz_recordingid", "musicbrainz_trackid", "MusicBrainz Track Id"
        ),
        "musicbrainz_release_id": _tag_value(
            tags, "musicbrainz_albumid", "MusicBrainz Album Id"
        ),
        "musicbrainz_release_group_id": _tag_value(
            tags, "musicbrainz_releasegroupid", "MusicBrainz Release Group Id"
        ),
        "musicbrainz_artist_id": _tag_value(
            tags, "musicbrainz_artistid", "MusicBrainz Artist Id"
        ),
        "musicbrainz_release_artist_id": _tag_value(
            tags, "musicbrainz_albumartistid", "MusicBrainz Album Artist Id"
        ),
        "compilation": _parse_bool(_first(tags.get("compilation") or easy.get("compilation"))),
        "isrc": _first(tags.get("isrc")),
    }

    lyrics = extract_lyrics(path, tags)
    metadata["lyrics"] = lyrics.text if lyrics else None
    metadata["lyrics_source"] = lyrics.source if lyrics else None
    metadata["lyrics_synced"] = lyrics.synchronized if lyrics else False
    metadata["artwork_status"] = _artwork_status(audio)
    metadata["metadata_hash"] = _metadata_hash(metadata)
    return metadata


def _artwork_status(audio) -> str:
    tags = audio.tags
    if not tags:
        return "missing"

    if getattr(tags, "getall", None) and tags.getall("APIC"):
        return "embedded"

    if "covr" in tags or "metadata_block_picture" in tags:
        return "embedded"

    pictures = getattr(audio, "pictures", None)
    return "embedded" if pictures else "missing"


def _metadata_hash(metadata: dict) -> str:
    excluded = {
        "path",
        "filename",
        "file_size",
        "modified_time",
        "metadata_hash",
        "artwork_status",
    }
    payload = {key: value for key, value in metadata.items() if key not in excluded}
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
