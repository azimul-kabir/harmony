"""Non-fatal Spotify artist genre enrichment with safe caching and diagnostics."""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from spotipy.exceptions import SpotifyException

from app.core.config import get_settings
from app.core.logging import logger
from app.domain.track import Track
from app.services.spotify.client import get_client

_ARTIST_ID = re.compile(r"^[A-Za-z0-9]{22}$")
_TTL_SECONDS = 3600
_NEGATIVE_TTL_SECONDS = 30
_CACHE: dict[str, tuple[float, list[str]]] = {}
_IN_FLIGHT: dict[str, threading.Event] = {}
_CACHE_LOCK = threading.Lock()


class GenreFailureCategory(StrEnum):
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    INVALID_REQUEST = "invalid_request"
    NETWORK_ERROR = "network_error"
    PROVIDER_ERROR = "provider_error"


@dataclass(slots=True)
class GenreLookupError:
    category: GenreFailureCategory
    http_status: int | None
    retryable: bool
    retry_after: str | None = None
    message: str | None = None


@dataclass(slots=True)
class GenreLookupResult:
    artists: dict[str, list[str]]
    error: GenreLookupError | None = None


@dataclass(slots=True)
class GenreResult:
    values: list[str]
    state: str
    source: str | None = None
    artist_id: str | None = None
    fallback: bool = False


def normalize_genres(values: list[str], maximum: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = str(value).strip()
        if value and value.casefold() not in seen:
            result.append(value)
            seen.add(value.casefold())
        if len(result) >= max(0, maximum):
            break
    return result


def enrich_tracks(tracks: list[Track], *, job_id: int | None = None) -> list[GenreResult]:
    settings = get_settings()
    if not settings.spotify_genre_fetch_enabled:
        return [GenreResult([], "genre_skipped_disabled") for _ in tracks]
    # Only 22-character Spotify artist IDs are ever sent to the artist endpoint.
    ids = list(dict.fromkeys(artist_id for track in tracks for artist_id in track.spotify_artist_ids if _valid_artist_id(artist_id)))
    lookup = _fetch_artists(ids, job_id=job_id)
    results: list[GenreResult] = []
    for track in tracks:
        result = resolve_track_genre(track, lookup.artists)
        # Existing/user-selected genres always win unless explicitly configured otherwise.
        if result.values and (not track.genre or settings.spotify_genre_replace_existing):
            track.genre = "; ".join(result.values)
            track.genre_provenance = json.dumps({"provider": "spotify", "source_entity": result.source,
                "source_spotify_artist_id": result.artist_id, "genres": result.values, "fallback_used": result.fallback})
        results.append(result)
    return results


def _valid_artist_id(value: object) -> bool:
    return isinstance(value, str) and bool(_ARTIST_ID.fullmatch(value))


def _fetch_artists(ids: list[str], *, job_id: int | None, client_factory: Callable = get_client) -> GenreLookupResult:
    """Fetch unique artist IDs, coalescing concurrent misses and never raising."""
    ids = list(dict.fromkeys(artist_id for artist_id in ids if _valid_artist_id(artist_id)))
    now = time.monotonic()
    output: dict[str, list[str]] = {}
    owners: list[str] = []
    waiting: list[threading.Event] = []
    with _CACHE_LOCK:
        for artist_id in ids:
            cached = _CACHE.get(artist_id)
            if cached and cached[0] > now:
                output[artist_id] = cached[1]
            elif artist_id in _IN_FLIGHT:
                waiting.append(_IN_FLIGHT[artist_id])
            else:
                event = threading.Event()
                _IN_FLIGHT[artist_id] = event
                owners.append(artist_id)
    logger.info("Spotify genre lookup job={} unique_artists={} cache_hits={} cache_misses={}", job_id, len(ids), len(output), len(ids) - len(output))
    for event in waiting:
        event.wait(timeout=15)
    if waiting:
        with _CACHE_LOCK:
            for artist_id in ids:
                cached = _CACHE.get(artist_id)
                if cached and cached[0] > time.monotonic():
                    output[artist_id] = cached[1]
    if not owners:
        return GenreLookupResult(output)

    error: GenreLookupError | None = None
    try:
        spotify = client_factory()
        # spotipy.Spotify.artists accepts a list; Spotify permits at most 50 IDs.
        for start in range(0, len(owners), 50):
            response = spotify.artists(owners[start:start + 50]) or {}
            for artist in response.get("artists", []) or []:
                if isinstance(artist, dict) and artist.get("id") in owners:
                    values = normalize_genres(artist.get("genres") or [], get_settings().spotify_genre_max_values)
                    output[artist["id"]] = values
        # A successful response with no artist / no genres is a valid cacheable result.
        with _CACHE_LOCK:
            for artist_id in owners:
                values = output.get(artist_id, [])
                output[artist_id] = values
                _CACHE[artist_id] = (time.monotonic() + _TTL_SECONDS, values)
    except Exception as exc:  # enrichment must never affect the download path
        error = _classify_error(exc)
        # Short negative cache prevents worker stampedes only for retryable outages.
        if error.retryable:
            with _CACHE_LOCK:
                for artist_id in owners:
                    _CACHE[artist_id] = (time.monotonic() + _NEGATIVE_TTL_SECONDS, [])
        logger.warning("Spotify genre lookup failed job={} unique_artists={} cache_hits={} cache_misses={} category={} http_status={} retryable={} retry_after={} detail={}",
            job_id, len(ids), len(output), len(ids) - len(output), error.category, error.http_status, error.retryable, error.retry_after, error.message)
    finally:
        with _CACHE_LOCK:
            for artist_id in owners:
                event = _IN_FLIGHT.pop(artist_id, None)
                if event:
                    event.set()
    return GenreLookupResult(output, error)


def _classify_error(exc: Exception) -> GenreLookupError:
    if isinstance(exc, SpotifyException):
        status = exc.http_status
        retry_after = _header(exc.headers, "Retry-After")
        category = {401: GenreFailureCategory.UNAUTHORIZED, 403: GenreFailureCategory.FORBIDDEN,
                    404: GenreFailureCategory.NOT_FOUND, 429: GenreFailureCategory.RATE_LIMITED,
                    400: GenreFailureCategory.INVALID_REQUEST}.get(status, GenreFailureCategory.PROVIDER_ERROR)
        return GenreLookupError(category, status, status == 429 or status is None or status >= 500, retry_after,
                                _safe_provider_message(exc.reason or exc.msg))
    return GenreLookupError(GenreFailureCategory.NETWORK_ERROR, None, True, message=type(exc).__name__)


def _safe_provider_message(value: object) -> str | None:
    """Keep a provider's concise diagnostic, without credentials or URLs."""
    if not value:
        return None
    text = str(value).replace("\n", " ").replace("\r", " ")
    text = re.sub(r"(?i)(bearer|basic)\s+[^\s,]+", r"\1 [redacted]", text)
    text = re.sub(r"(?i)(client_secret|access_token|token|password)=([^&\s]+)", r"\1=[redacted]", text)
    text = re.sub(r"https?://[^\s]+", "[url redacted]", text)
    return text[:240]


def _header(headers: object, name: str) -> str | None:
    if not headers:
        return None
    for key, value in headers.items():
        if str(key).casefold() == name.casefold():
            return str(value)
    return None


def resolve_track_genre(track: Track, artists: dict[str, list[str]]) -> GenreResult:
    settings = get_settings()
    ids = [artist_id for artist_id in track.spotify_artist_ids if _valid_artist_id(artist_id)]
    if not ids:
        return GenreResult([], "genre_unavailable")
    primary = normalize_genres(artists.get(ids[0], []), settings.spotify_genre_max_values)
    featured = ids[1:]
    if primary:
        if settings.spotify_genre_merge_featured:
            primary = normalize_genres(primary + [genre for artist_id in featured for genre in artists.get(artist_id, [])], settings.spotify_genre_max_values)
        return GenreResult(primary, "genre_resolved", "primary_artist", ids[0])
    if settings.spotify_genre_include_featured_fallback:
        featured_values = normalize_genres([genre for artist_id in featured for genre in artists.get(artist_id, [])], settings.spotify_genre_max_values)
        if featured_values:
            return GenreResult(featured_values, "genre_resolved", "featured_artist_fallback", featured[0], True)
    if track.genre:
        return GenreResult(normalize_genres(track.genre.split(";"), settings.spotify_genre_max_values), "genre_existing_retained")
    return GenreResult([], "genre_unavailable")
