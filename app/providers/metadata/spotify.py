"""Bounded Spotify recording metadata provider."""

from __future__ import annotations

import asyncio
import re
import threading
from datetime import datetime, timezone
from typing import Any, Callable

from spotipy.exceptions import SpotifyException

from app.core.config import Settings, get_settings
from app.core.logging import logger
from app.domain.metadata.provider import CandidatePage, ExternalId, ProviderCandidate, RecordingCandidate
from app.providers.metadata.base import EntityType, MetadataProvider, ProgressCallback, ProviderCapabilities, SearchType
from app.providers.metadata.errors import ProviderError
from app.services.spotify.client import get_client

PROVIDER = "spotify"
_TRACK_ID = re.compile(r"^[A-Za-z0-9]{22}$")


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def normalize_recording(data: dict[str, Any]) -> RecordingCandidate:
    track_id, title = _text(data.get("id")), _text(data.get("name"))
    album = data.get("album") if isinstance(data.get("album"), dict) else {}
    artists = data.get("artists") if isinstance(data.get("artists"), list) else []
    album_artists = album.get("artists") if isinstance(album.get("artists"), list) else []
    artist_names = [_text(item.get("name")) for item in artists if isinstance(item, dict)]
    album_artist_names = [_text(item.get("name")) for item in album_artists if isinstance(item, dict)]
    if not track_id or not title:
        raise ProviderError(
            "malformed_response", "Spotify track omitted required identity or title",
            provider=PROVIDER, operation="normalize_recording",
        )
    release_date = _text(album.get("release_date"))
    external = data.get("external_ids") if isinstance(data.get("external_ids"), dict) else {}
    isrc = _text(external.get("isrc"))
    duration = data.get("duration_ms")
    return RecordingCandidate(
        provider=PROVIDER,
        provider_entity_id=track_id,
        title=title,
        artist=", ".join(value for value in artist_names if value) or None,
        album=_text(album.get("name")),
        album_artist=", ".join(value for value in album_artist_names if value) or None,
        duration_seconds=duration / 1000 if isinstance(duration, (int, float)) else None,
        track_number=data.get("track_number") if isinstance(data.get("track_number"), int) else None,
        disc_number=data.get("disc_number") if isinstance(data.get("disc_number"), int) else None,
        total_tracks=album.get("total_tracks") if isinstance(album.get("total_tracks"), int) else None,
        release_date=release_date,
        original_release_date=release_date,
        year=int(release_date[:4]) if release_date and release_date[:4].isdigit() else None,
        isrc=isrc,
        external_ids=(ExternalId(namespace="isrc", value=isrc),) if isrc else (),
        release_context="spotify_album" if album else None,
    )


class SpotifyMetadataProvider(MetadataProvider):
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client_factory: Callable[[], Any] = get_client,
    ):
        self.settings = settings or get_settings()
        self.client_factory = client_factory
        self.configured = bool(self.settings.spotify_client_id and self.settings.spotify_client_secret)
        self._state_lock = threading.Lock()
        self._last_request = self._last_error = None
        self._last_latency_ms = None

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            PROVIDER, ("recording",), ("recording",), True, False, False, False
        )

    def _require(self, entity_type: str, *, operation: str) -> None:
        if not self.configured:
            raise ProviderError(
                "not_configured", "Spotify metadata requires configured client credentials.",
                provider=PROVIDER, operation=operation,
            )
        supported = self.capabilities.search if operation == "search" else self.capabilities.lookup
        if entity_type not in supported:
            raise ProviderError(
                "validation_failure", "Spotify metadata currently supports recordings only.",
                provider=PROVIDER, operation=operation,
            )

    async def search(
        self, entity_type: SearchType, query: str, *, limit: int = 25,
        offset: int = 0, force_refresh: bool = False, bypass_cache: bool = False,
        cancel_event: asyncio.Event | None = None,
        progress: ProgressCallback | None = None,
    ) -> CandidatePage:
        self._require(entity_type, operation="search")
        query = query.strip()
        if not query or not 1 <= limit <= 50 or not 0 <= offset <= 1000:
            raise ProviderError(
                "validation_failure", "Invalid Spotify query, limit, or offset.",
                provider=PROVIDER, operation="search",
            )
        if cancel_event and cancel_event.is_set():
            raise ProviderError("cancelled", "Provider request was cancelled.", provider=PROVIDER, operation="search")
        started = asyncio.get_running_loop().time()
        try:
            payload = await asyncio.to_thread(
                self.client_factory().search,
                q=query, type="track", limit=limit, offset=offset,
            )
            if cancel_event and cancel_event.is_set():
                raise ProviderError("cancelled", "Provider request was cancelled.", provider=PROVIDER, operation="search")
            tracks = payload.get("tracks") if isinstance(payload, dict) else None
            rows = tracks.get("items") if isinstance(tracks, dict) else None
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ProviderError("malformed_response", "Spotify returned invalid track results.", provider=PROVIDER, operation="search")
            items = [normalize_recording(row) for row in rows]
            total = tracks.get("total") if isinstance(tracks.get("total"), int) else offset + len(items)
            page = CandidatePage(items=items, offset=offset, limit=limit, total=total)
            self._record("search", (asyncio.get_running_loop().time() - started) * 1000, None)
            if progress:
                progress(len(items), total)
            return page
        except SpotifyException as error:
            raise self._provider_error(error, "search") from error
        except ProviderError as error:
            self._record("search", None, error.code)
            raise
        except Exception as error:
            self._record("search", None, "provider_failure")
            raise ProviderError(
                "provider_failure", "Spotify could not complete the metadata request.",
                provider=PROVIDER, operation="search", retryable=True,
            ) from error

    async def lookup(
        self, entity_type: EntityType, entity_id: str, *,
        force_refresh: bool = False, bypass_cache: bool = False,
        cancel_event: asyncio.Event | None = None,
        progress: ProgressCallback | None = None,
    ) -> ProviderCandidate:
        self._require(entity_type, operation="lookup")
        entity_id = entity_id.strip()
        if not _TRACK_ID.fullmatch(entity_id):
            raise ProviderError("validation_failure", "Invalid Spotify track ID.", provider=PROVIDER, operation="lookup")
        if cancel_event and cancel_event.is_set():
            raise ProviderError("cancelled", "Provider request was cancelled.", provider=PROVIDER, operation="lookup")
        started = asyncio.get_running_loop().time()
        try:
            payload = await asyncio.to_thread(self.client_factory().track, entity_id)
            if cancel_event and cancel_event.is_set():
                raise ProviderError("cancelled", "Provider request was cancelled.", provider=PROVIDER, operation="lookup")
            if not isinstance(payload, dict):
                raise ProviderError("malformed_response", "Spotify returned invalid track data.", provider=PROVIDER, operation="lookup")
            item = normalize_recording(payload)
            self._record("lookup", (asyncio.get_running_loop().time() - started) * 1000, None)
            if progress:
                progress(1, 1)
            return item
        except SpotifyException as error:
            raise self._provider_error(error, "lookup") from error
        except ProviderError as error:
            self._record("lookup", None, error.code)
            raise
        except Exception as error:
            self._record("lookup", None, "provider_failure")
            raise ProviderError(
                "provider_failure", "Spotify could not complete the metadata request.",
                provider=PROVIDER, operation="lookup", retryable=True,
            ) from error

    def _provider_error(self, error: SpotifyException, operation: str) -> ProviderError:
        code = "not_found" if error.http_status == 404 else "rate_limited" if error.http_status == 429 else "authentication_failure" if error.http_status in {401, 403} else "provider_failure"
        retryable = error.http_status == 429 or bool(error.http_status and error.http_status >= 500)
        result = ProviderError(code, "Spotify could not complete the metadata request.", provider=PROVIDER, operation=operation, retryable=retryable)
        self._record(operation, None, code)
        return result

    def _record(self, operation: str, latency: float | None, error: str | None) -> None:
        with self._state_lock:
            self._last_request = {
                "operation": operation, "cache_hit": False, "retry_count": 0,
                "status": "error" if error else "ok",
                "at": datetime.now(timezone.utc).isoformat(),
            }
            self._last_latency_ms = latency
            if error:
                self._last_error = {"code": error, "operation": operation}
        logger.info("provider={} operation={} latency_ms={} status={}", PROVIDER, operation, latency, "error" if error else "ok")

    def status(self) -> dict:
        with self._state_lock:
            state = {
                "last_request": self._last_request,
                "last_error": self._last_error,
                "search_latency_ms": self._last_latency_ms,
            }
        return {
            "provider": PROVIDER,
            "available": self.configured,
            "configured": self.configured,
            "rate_limit": {"requests_per_second": None},
            "cache": {"fresh_entries": 0, "stale_entries": 0, "hits": 0, "misses": 0},
            **state,
        }

    async def close(self) -> None:
        return None
