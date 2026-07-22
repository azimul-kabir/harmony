"""Spotify artist-genre enrichment.

Spotify's track and album endpoints intentionally do not carry genres.  This
module is the single place where artist genres are fetched and selected.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.logging import logger
from app.domain.track import Track
from app.services.spotify.client import get_client

_CACHE: dict[str, tuple[float, list[str]]] = {}
_TTL_SECONDS = 3600

def normalize_genres(values: list[str], maximum: int) -> list[str]:
    result: list[str] = []; seen: set[str] = set()
    for value in values:
        value = str(value).strip()
        if value and value.casefold() not in seen:
            result.append(value); seen.add(value.casefold())
        if len(result) >= max(0, maximum): break
    return result

@dataclass(slots=True)
class GenreResult:
    values: list[str]
    state: str
    source: str | None = None
    artist_id: str | None = None
    fallback: bool = False

def enrich_tracks(tracks: list[Track], *, job_id: int | None = None) -> list[GenreResult]:
    settings = get_settings()
    if not settings.spotify_genre_fetch_enabled:
        return [GenreResult([], "genre_skipped_disabled") for _ in tracks]
    ids = list(dict.fromkeys(artist_id for track in tracks for artist_id in track.spotify_artist_ids))
    artists = _fetch_artists(ids, job_id=job_id)
    results = []
    for track in tracks:
        result = resolve_track_genre(track, artists)
        if result.values:
            track.genre = "; ".join(result.values)
            track.genre_provenance = json.dumps({"provider": "spotify", "source_entity": result.source,
                "source_spotify_artist_id": result.artist_id, "genres": result.values, "fallback_used": result.fallback})
        results.append(result)
    return results

def _fetch_artists(ids: list[str], *, job_id: int | None) -> dict[str, list[str]]:
    now = time.monotonic(); output: dict[str, list[str]] = {}; missing = []
    for artist_id in ids:
        cached = _CACHE.get(artist_id)
        if cached and cached[0] > now: output[artist_id] = cached[1]
        else: missing.append(artist_id)
    logger.info("Spotify genre lookup job={} unique_artists={} cache_hits={} cache_misses={}", job_id, len(ids), len(output), len(missing))
    if not missing: return output
    try:
        spotify = get_client()
        # Spotify's documented batch endpoint permits up to 50 IDs.
        for start in range(0, len(missing), 50):
            response = spotify.artists(missing[start:start + 50]) or {}
            for artist in response.get("artists", []) or []:
                if not isinstance(artist, dict) or not artist.get("id"): continue
                values = normalize_genres(artist.get("genres") or [], get_settings().spotify_genre_max_values)
                output[artist["id"]] = values; _CACHE[artist["id"]] = (now + _TTL_SECONDS, values)
        # Missing/deleted artists are valid empty outcomes and are cached too.
        for artist_id in missing:
            if artist_id not in output: output[artist_id] = []; _CACHE[artist_id] = (now + _TTL_SECONDS, [])
    except Exception as exc:
        logger.warning("Spotify genre lookup failed job={} category={}", job_id, type(exc).__name__)
    return output

def resolve_track_genre(track: Track, artists: dict[str, list[str]]) -> GenreResult:
    settings = get_settings(); ids = track.spotify_artist_ids
    if not ids: return GenreResult([], "genre_unavailable")
    primary = normalize_genres(artists.get(ids[0], []), settings.spotify_genre_max_values)
    featured = ids[1:]
    if primary:
        if settings.spotify_genre_merge_featured:
            primary = normalize_genres(primary + [genre for artist_id in featured for genre in artists.get(artist_id, [])], settings.spotify_genre_max_values)
        return GenreResult(primary, "genre_resolved", "primary_artist", ids[0])
    if settings.spotify_genre_include_featured_fallback:
        featured_values = [genre for artist_id in featured for genre in artists.get(artist_id, [])]
        featured_values = normalize_genres(featured_values, settings.spotify_genre_max_values)
        if featured_values: return GenreResult(featured_values, "genre_resolved", "featured_artist_fallback", featured[0], True)
    if track.genre: return GenreResult(normalize_genres(track.genre.split(";"), settings.spotify_genre_max_values), "genre_existing_retained")
    return GenreResult([], "genre_unavailable")
