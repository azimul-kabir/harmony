"""Small, explicit metadata editing and MusicBrainz lookup helpers."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
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
    values = {
        field: value.strip().replace('"', r'\"')
        for field, value in (("recording", title), ("artist", artist), ("release", album))
        if value and value.strip()
    }
    # A recording title and artist identify a track more reliably than its
    # release name. Library tags commonly contain a translated, shortened, or
    # misspelled album name; making all three clauses mandatory causes
    # MusicBrainz to return no recordings even when title + artist is an exact
    # match. Use the album only when one of those primary fields is unavailable.
    fields = (
        ("recording", "artist")
        if "recording" in values and "artist" in values
        else tuple(values)
    )
    terms = [f'{field}:"{values[field]}"' for field in fields]
    if not terms:
        raise ValueError("Enter a title, artist, or album to search.")
    settings = get_settings()
    query = urlencode({"query": " AND ".join(terms), "fmt": "json", "limit": 8})
    # MusicBrainz treats ``recording`` as the collection search endpoint. A
    # trailing slash instead addresses an empty recording ID and is rejected
    # by the production API.
    url = f"{settings.musicbrainz_base_url.rstrip('/')}/recording?{query}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Harmony/3.0.0 (https://github.com/azimul-kabir/harmony)",
        },
    )
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
