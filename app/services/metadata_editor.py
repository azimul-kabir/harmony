"""Small, explicit metadata editing and MusicBrainz lookup helpers."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from mutagen import File

from app.core.config import get_settings


EDITABLE_TAGS = {
    "title": "title",
    "artist": "artist",
    "album": "album",
    "album_artist": "albumartist",
    "genre": "genre",
    "year": "date",
    "track": "tracknumber",
    "disc": "discnumber",
}


def write_metadata(path: str | Path, values: dict) -> None:
    """Write only the user-facing tags, preserving unrelated provider tags."""
    audio = File(Path(path), easy=True)
    if audio is None:
        raise ValueError("This audio format does not support metadata editing.")
    if audio.tags is None:
        audio.add_tags()
    for field, tag in EDITABLE_TAGS.items():
        value = values.get(field)
        if value in (None, ""):
            audio.tags.pop(tag, None)
        else:
            audio[tag] = [str(value)]
    audio.save()


def search_musicbrainz(*, title: str | None, artist: str | None, album: str | None) -> list[dict]:
    terms = []
    for field, value in (("recording", title), ("artist", artist), ("release", album)):
        if value and value.strip():
            escaped = value.strip().replace('"', r'\"')
            terms.append(f'{field}:"{escaped}"')
    if not terms:
        raise ValueError("Enter a title, artist, or album to search.")
    settings = get_settings()
    url = f"{settings.musicbrainz_base_url.rstrip('/')}/recording/?query={quote(' AND '.join(terms))}&fmt=json&limit=8"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "Harmony/3.0 metadata-editor"})
    try:
        with urlopen(request, timeout=settings.musicbrainz_timeout_seconds) as response:
            payload = json.load(response)
    except (HTTPError, URLError, OSError, ValueError) as error:
        raise ValueError("MusicBrainz search is temporarily unavailable.") from error

    results = []
    for recording in payload.get("recordings", []):
        artists = recording.get("artist-credit") or []
        artist_name = "".join(part.get("name", part) if isinstance(part, dict) else str(part) for part in artists)
        releases = recording.get("releases") or []
        release = releases[0] if releases else {}
        media = release.get("media") or []
        track = ((media[0].get("track") or [{}])[0] if media else {})
        date = release.get("date") or recording.get("first-release-date") or ""
        release_id = release.get("id")
        results.append({
            "source": "MusicBrainz",
            "recording_id": recording.get("id"),
            "release_id": release_id,
            "title": recording.get("title"),
            "artist": artist_name or None,
            "album": release.get("title"),
            "album_artist": artist_name or None,
            "year": int(date[:4]) if date[:4].isdigit() else None,
            "track": track.get("number"),
            "disc": media[0].get("position") if media else None,
            "score": recording.get("score"),
            "artwork_url": (
                f"{settings.cover_art_archive_base_url.rstrip('/')}/release/{release_id}/front-250"
                if release_id else None
            ),
        })
    return results
