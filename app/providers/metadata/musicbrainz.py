from __future__ import annotations

import asyncio
import re
import threading
from datetime import datetime, timezone
from urllib.parse import urlparse
from typing import Any

from pydantic import TypeAdapter, ValidationError

from app.core.config import Settings, get_settings
from app.core.logging import logger
from app.domain.metadata.provider import (
    ArtistCandidate, CandidatePage, ExternalId, ProviderCandidate, RecordingCandidate,
    Relationship, ReleaseCandidate, ReleaseGroupCandidate,
)
from app.providers.metadata.base import EntityType, MetadataProvider, ProgressCallback, ProviderCapabilities, SearchType
from app.providers.metadata.cache import ProviderCache
from app.providers.metadata.errors import ProviderError
from app.providers.metadata.http import ProviderHttpClient, RetryPolicy
from app.providers.metadata.rate_limit import AsyncRateLimiter

PROVIDER = "musicbrainz"
PROVIDER_VERSION = "ws2-normalization-v2"
_MBID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
_candidate_adapter = TypeAdapter(ProviderCandidate)


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _artist_credit(data: dict) -> str | None:
    credits = data.get("artist-credit") or []
    if not isinstance(credits, list): return None
    parts = []
    for item in credits:
        if not isinstance(item, dict): continue
        artist = item.get("artist") if isinstance(item.get("artist"), dict) else {}
        name = _text(item.get("name")) or _text(artist.get("name"))
        if name: parts.append(name + (item.get("joinphrase") if isinstance(item.get("joinphrase"), str) else ""))
    return "".join(parts).strip() or None


def _artist_credit_id(data: dict) -> str | None:
    credits=data.get("artist-credit") or []
    if not isinstance(credits,list): return None
    for item in credits:
        artist=item.get("artist") if isinstance(item,dict) else None
        value=_text(artist.get("id")) if isinstance(artist,dict) else None
        if value: return value
    return None


def _aliases(data: dict) -> tuple[str, ...]:
    values = {_text(x.get("name")) for x in data.get("aliases", []) if isinstance(x, dict)}
    return tuple(sorted(x for x in values if x))


def _genres(data: dict) -> tuple[str, ...]:
    values = {_text(x.get("name")) for key in ("genres", "tags") for x in data.get(key, []) if isinstance(x, dict)}
    return tuple(sorted(x for x in values if x))


def _external_ids(data: dict) -> tuple[ExternalId, ...]:
    values: set[tuple[str, str]] = set()
    for isrc in data.get("isrcs", []):
        if _text(isrc): values.add(("isrc", isrc.strip()))
    for ipi in data.get("ipis", []):
        if _text(ipi): values.add(("ipi", ipi.strip()))
    for isn in data.get("isnis", []):
        if _text(isn): values.add(("isni", isn.strip()))
    return tuple(ExternalId(namespace=k, value=v) for k, v in sorted(values))


def _relationships(data: dict) -> tuple[Relationship, ...]:
    result: list[Relationship] = []
    for relation in data.get("relations", []):
        if not isinstance(relation, dict): continue
        target_type = _text(relation.get("target-type"))
        target = relation.get(target_type) if target_type else None
        if not isinstance(target, dict): continue
        target_id, relation_type = _text(target.get("id")), _text(relation.get("type"))
        if not target_id or not relation_type: continue
        result.append(Relationship(relation_type=relation_type, target_type=target_type or "unknown",
            target_id=target_id, target_name=_text(target.get("name")) or _text(target.get("title")),
            direction=_text(relation.get("direction"))))
    return tuple(result)


def _release_group(data: dict) -> dict:
    value = data.get("release-group")
    return value if isinstance(value, dict) else {}


def _first_release(data: dict) -> dict:
    releases = data.get("releases")
    return releases[0] if isinstance(releases, list) and releases and isinstance(releases[0], dict) else {}


def _track_context(release: dict) -> tuple[int | None, int | None]:
    media = release.get("media") if isinstance(release.get("media"), list) else []
    for medium in media:
        if not isinstance(medium, dict): continue
        tracks = medium.get("tracks") if isinstance(medium.get("tracks"), list) else []
        if tracks:
            track = tracks[0] if isinstance(tracks[0], dict) else {}
            position = track.get("position") if isinstance(track.get("position"), int) else None
            disc = medium.get("position") if isinstance(medium.get("position"), int) else None
            return position, disc
    return None, None


def _release_counts(release: dict) -> tuple[int | None,int | None]:
    media=release.get("media") if isinstance(release.get("media"),list) else []
    counts=[x.get("track-count") for x in media if isinstance(x,dict) and isinstance(x.get("track-count"),int)]
    return (sum(counts) or None,len(media) or None)


def normalize(entity_type: EntityType, data: dict) -> ProviderCandidate:
    entity_id, title = _text(data.get("id")), _text(data.get("title")) or _text(data.get("name"))
    if not entity_id or not title:
        raise ProviderError("malformed_response", "Provider entity omitted required identity or title",
                            provider=PROVIDER, operation=f"normalize_{entity_type}")
    common = dict(provider=PROVIDER, provider_entity_id=entity_id, title=title,
        aliases=_aliases(data), genres=_genres(data), external_ids=_external_ids(data),
        relationships=_relationships(data))
    if entity_type == "artist":
        return ArtistCandidate(**common, sort_name=_text(data.get("sort-name")), artist_type=_text(data.get("type")),
            country=_text(data.get("country")), disambiguation=_text(data.get("disambiguation")))
    if entity_type == "release_group":
        secondary = data.get("secondary-types") if isinstance(data.get("secondary-types"), list) else []
        return ReleaseGroupCandidate(**common, artist=_artist_credit(data), primary_type=_text(data.get("primary-type")),
            secondary_types=tuple(x for x in secondary if isinstance(x, str)), first_release_date=_text(data.get("first-release-date")))
    if entity_type == "release":
        group = _release_group(data)
        media = data.get("media") if isinstance(data.get("media"), list) else []
        track_count = sum(x.get("track-count", 0) for x in media if isinstance(x, dict) and isinstance(x.get("track-count"), int)) or None
        return ReleaseCandidate(**common, artist=_artist_credit(data), release_date=_text(data.get("date")),
            release_group=_text(group.get("title")), track_count=track_count, disc_count=len(media) or None)
    release = _first_release(data)
    group = _release_group(release)
    track, disc = _track_context(release)
    total_tracks,total_discs=_release_counts(release)
    length = data.get("length")
    release_date=_text(release.get("date"));original_date=_text(group.get("first-release-date"))
    secondary=group.get("secondary-types") if isinstance(group.get("secondary-types"),list) else []
    isrcs=[_text(x) for x in data.get("isrcs",[]) if _text(x)]
    return RecordingCandidate(**common, artist=_artist_credit(data), album=_text(release.get("title")),
        duration_seconds=length / 1000 if isinstance(length, (int, float)) else None,
        track_number=track, disc_number=disc, release_date=_text(release.get("date")),
        release_group=_text(group.get("title")),album_artist=_artist_credit(release),total_tracks=total_tracks,total_discs=total_discs,
        original_release_date=original_date,year=int(release_date[:4]) if release_date and release_date[:4].isdigit() else None,
        isrc=isrcs[0] if len(isrcs)==1 else None,recording_disambiguation=_text(data.get("disambiguation")),
        release_disambiguation=_text(release.get("disambiguation")),compilation=True if "Compilation" in secondary else None,
        release_id=_text(release.get("id")),release_group_id=_text(group.get("id")),artist_id=_artist_credit_id(data),
        release_artist_id=_artist_credit_id(release),release_context="first_normalized_release" if release else None)


class MusicBrainzProvider(MetadataProvider):
    def __init__(self, settings: Settings | None = None, *, transport=None, limiter=None, sleep=asyncio.sleep, random_fn=None):
        settings = settings or get_settings()
        self.cache = ProviderCache(PROVIDER, settings.musicbrainz_cache_ttl_seconds, PROVIDER_VERSION)
        configured_rps = settings.musicbrainz_requests_per_second
        effective_rps = min(configured_rps, 1.0) if urlparse(settings.musicbrainz_base_url).hostname == "musicbrainz.org" else configured_rps
        self.limiter = limiter or AsyncRateLimiter(effective_rps, sleep=sleep)
        kwargs = {} if random_fn is None else {"random_fn": random_fn}
        self.http = ProviderHttpClient(provider=PROVIDER, base_url=settings.musicbrainz_base_url,
            user_agent=settings.musicbrainz_user_agent, timeout=settings.musicbrainz_timeout_seconds,
            retry=RetryPolicy(settings.musicbrainz_max_retries, settings.musicbrainz_backoff_seconds),
            limiter=self.limiter, max_concurrent=settings.musicbrainz_max_concurrent_requests,
            transport=transport, sleep=sleep, **kwargs)
        self._state_lock = threading.Lock()
        self._last_request = self._last_error = None
        self._last_latency_ms = None

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(PROVIDER, ("recording", "release", "artist"),
            ("recording", "release", "release_group", "artist"), True, True, True, True)

    async def search(self, entity_type: SearchType, query: str, *, limit: int = 25, offset: int = 0,
                     force_refresh: bool = False, bypass_cache: bool = False,
                     cancel_event: asyncio.Event | None = None, progress: ProgressCallback | None = None) -> CandidatePage:
        query = query.strip()
        if entity_type not in self.capabilities.search or not query or not 1 <= limit <= 100 or offset < 0:
            raise ProviderError("validation_failure", "Invalid search type, query, limit, or offset",
                                provider=PROVIDER, operation="search")
        key = self.cache.key(f"search:{entity_type}", query=query, limit=limit, offset=offset)
        cached = self.cache.get(key, bypass=bypass_cache or force_refresh)
        if cached.data is not None:
            self._record("search", 0, None, True)
            return CandidatePage.model_validate(cached.data)
        operation = f"search_{entity_type}"
        try:
            payload, retries, latency = await self.http.get_json(entity_type, params={"query": query, "fmt": "json", "limit": limit, "offset": offset}, operation=operation, cancel_event=cancel_event)
            plural = {"release": "releases", "recording": "recordings", "artist": "artists"}[entity_type]
            rows = payload.get(plural)
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ProviderError("malformed_response", f"Provider response contained invalid {plural}", provider=PROVIDER, operation=operation)
            items = [normalize(entity_type, row) for row in rows]
            total = payload.get("count") if isinstance(payload.get("count"), int) else offset + len(items)
            page = CandidatePage(items=items, offset=offset, limit=limit, total=total)
            self.cache.put(key, f"search:{entity_type}", page.model_dump(mode="json"), query=query)
            self._record(operation, latency, None, False, retries)
            if progress: progress(len(items), total)
            return page
        except (ProviderError, ValidationError) as exc:
            error = exc if isinstance(exc, ProviderError) else ProviderError("malformed_response", "Provider data failed normalization", provider=PROVIDER, operation=operation)
            self._record(operation, None, error.code, False)
            raise error from exc

    async def lookup(self, entity_type: EntityType, entity_id: str, *, force_refresh: bool = False,
                     bypass_cache: bool = False, cancel_event: asyncio.Event | None = None,
                     progress: ProgressCallback | None = None) -> ProviderCandidate:
        entity_id = entity_id.strip()
        if entity_type not in self.capabilities.lookup or not _MBID.fullmatch(entity_id):
            raise ProviderError("validation_failure", "Invalid lookup type or MusicBrainz identifier", provider=PROVIDER, operation="lookup")
        key = self.cache.key(f"lookup:{entity_type}", entity_id=entity_id)
        cached = self.cache.get(key, bypass=bypass_cache or force_refresh)
        if cached.data is not None:
            self._record("lookup", 0, None, True)
            return _candidate_adapter.validate_python(cached.data)
        path_type = "release-group" if entity_type == "release_group" else entity_type
        includes = {"recording": "artist-credits+releases+release-groups+media+genres+isrcs+url-rels+artist-rels",
            "release": "artist-credits+release-groups+recordings+media+isrcs+genres+url-rels+artist-rels",
            "release_group": "artist-credits+releases+genres+url-rels+artist-rels",
            "artist": "aliases+genres+tags+url-rels+artist-rels"}[entity_type]
        operation = f"lookup_{entity_type}"
        try:
            payload, retries, latency = await self.http.get_json(f"{path_type}/{entity_id}", params={"fmt": "json", "inc": includes}, operation=operation, cancel_event=cancel_event)
            item = normalize(entity_type, payload)
            self.cache.put(key, f"lookup:{entity_type}", item.model_dump(mode="json"), entity_id=entity_id)
            self._record(operation, latency, None, False, retries)
            if progress: progress(1, 1)
            return item
        except (ProviderError, ValidationError) as exc:
            error = exc if isinstance(exc, ProviderError) else ProviderError("malformed_response", "Provider data failed normalization", provider=PROVIDER, operation=operation)
            self._record(operation, None, error.code, False)
            raise error from exc

    def _record(self, operation: str, latency: float | None, error: str | None, cache_hit: bool, retries: int = 0) -> None:
        with self._state_lock:
            self._last_request = {"operation": operation, "cache_hit": cache_hit, "retry_count": retries,
                                  "status": "error" if error else "ok", "at": datetime.now(timezone.utc).isoformat()}
            self._last_latency_ms = latency
            if error: self._last_error = {"code": error, "operation": operation}
        logger.info("provider={} operation={} latency_ms={} status={} retries={} cache_hit={}",
            PROVIDER, operation, latency, "error" if error else "ok", retries, cache_hit)

    def status(self) -> dict:
        with self._state_lock:
            state = {"last_request": self._last_request, "last_error": self._last_error, "search_latency_ms": self._last_latency_ms}
        return {"provider": PROVIDER, "available": not self.http._closed, "rate_limit": self.limiter.status(),
                "cache": self.cache.stats(), **state}

    async def close(self) -> None:
        await self.http.close()
