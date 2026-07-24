"""Non-fatal Spotify artist-genre enrichment for Spotify Development Mode.

Spotify artist genres are deprecated and may disappear in a future API revision.
"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from spotipy.exceptions import SpotifyException

from app.core.config import get_settings
from app.core.logging import logger
from app.database.models import AppSetting
from app.database.session import SessionLocal
from app.domain.track import Track
from app.services.spotify.client import get_client

_ARTIST_ID = re.compile(r"^[A-Za-z0-9]{22}$")
_TTL_SECONDS = 3600
_NEGATIVE_TTL_SECONDS = 30
_AUTH_FAILURE_TTL_SECONDS = 300
_CACHE: dict[str, tuple[float, list[str]]] = {}
_IN_FLIGHT: dict[str, threading.Event] = {}
_CACHE_LOCK = threading.Lock()


class GenreFailureCategory(StrEnum):
    DISABLED = "disabled"
    CREDENTIALS_MISSING = "credentials_missing"
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
    # Only 22-character Spotify artist IDs are ever sent to the artist endpoint.
    ids = list(dict.fromkeys(artist_id for track in tracks for artist_id in track.spotify_artist_ids if _valid_artist_id(artist_id)))
    lookup = _fetch_artists(ids, job_id=job_id)
    if lookup.error and lookup.error.category == GenreFailureCategory.DISABLED:
        # Do not turn an existing embedded or user-selected value into an empty
        # Spotify result, and do not change its provenance while disabled.
        return [GenreResult([], "genre_skipped_disabled") for _ in tracks]
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
    """Fetch unique artists individually; Development Mode no longer permits GET /artists?ids."""
    # This is intentionally the shared, first entry point for every artist
    # lookup (downloads, refreshes, bulk work, and the diagnostic command).
    # It must run before cache work, client construction, or authentication.
    settings = get_settings()
    if not _genre_enrichment_enabled(settings.spotify_genre_enrichment_enabled):
        return GenreLookupResult({}, GenreLookupError(GenreFailureCategory.DISABLED, None, False))
    if not settings.spotify_client_id or not settings.spotify_client_secret:
        logger.warning("Spotify genre enrichment is enabled but Spotify credentials are not configured; continuing without Spotify genres")
        return GenreLookupResult({}, GenreLookupError(GenreFailureCategory.CREDENTIALS_MISSING, None, False))
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

    def fetch_one(artist_id: str) -> tuple[str, list[str] | None, GenreLookupError | None]:
        try:
            # Development Mode requires the individual GET /v1/artists/{id} endpoint.
            artist = client_factory().artist(artist_id) or {}
            values = normalize_genres(artist.get("genres") or [], settings.spotify_genre_max_values)
            return artist_id, values, None
        except Exception as exc:  # enrichment must never affect the download path
            return artist_id, None, _classify_error(exc)

    error: GenreLookupError | None = None
    limit = max(1, settings.spotify_genre_max_concurrent_requests)
    try:
        with ThreadPoolExecutor(max_workers=limit, thread_name_prefix="spotify-genre") as executor:
            futures = [executor.submit(fetch_one, artist_id) for artist_id in owners]
            for future in as_completed(futures):
                artist_id, values, request_error = future.result()
                if request_error is None:
                    output[artist_id] = values or []
                    with _CACHE_LOCK:
                        _CACHE[artist_id] = (time.monotonic() + _TTL_SECONDS, output[artist_id])
                else:
                    error = error or request_error
                    # Do not permanently cache outages or credential failures, but suppress
                    # repeated track-level calls long enough for a task to complete.
                    ttl = _NEGATIVE_TTL_SECONDS if request_error.retryable else _AUTH_FAILURE_TTL_SECONDS if request_error.category in (GenreFailureCategory.UNAUTHORIZED, GenreFailureCategory.FORBIDDEN) else 0
                    if ttl:
                        output[artist_id] = []
                        with _CACHE_LOCK:
                            _CACHE[artist_id] = (time.monotonic() + ttl, [])
                    logger.warning("Spotify genre lookup failed job={} unique_artists={} cache_hits={} cache_misses={} category={} http_status={} retryable={} retry_after={} detail={}",
                        job_id, len(ids), len(output), len(ids) - len(output), request_error.category, request_error.http_status, request_error.retryable, request_error.retry_after, request_error.message)
    finally:
        with _CACHE_LOCK:
            for artist_id in owners:
                event = _IN_FLIGHT.pop(artist_id, None)
                if event:
                    event.set()
    return GenreLookupResult(output, error)


def _genre_enrichment_enabled(configured_default: bool) -> bool:
    """Use the persistent Settings toggle when present, otherwise the env default."""
    db = SessionLocal()
    try:
        try:
            setting = db.get(AppSetting, "spotify_genre_enrichment_enabled")
        except Exception:
            # The diagnostic also runs before a database is bootstrapped. The
            # environment default remains authoritative in that situation.
            return configured_default
        return configured_default if setting is None else setting.value.casefold() in ("true", "1", "yes", "on")
    finally:
        db.close()

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
