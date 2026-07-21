import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.database.models import ProviderCacheEntry
from app.database.session import SessionLocal
from app.domain.metadata.provider import ArtistCandidate, RecordingCandidate
from app.main import app
from app.providers.metadata.base import MetadataProvider
from app.providers.metadata.errors import ProviderCancelledError, ProviderError
from app.providers.metadata.musicbrainz import MusicBrainzProvider, normalize
from app.providers.metadata.rate_limit import AsyncRateLimiter


def settings(**values):
    defaults = dict(musicbrainz_cache_ttl_seconds=60, musicbrainz_max_retries=2,
        musicbrainz_backoff_seconds=0, musicbrainz_requests_per_second=100000,
        musicbrainz_max_concurrent_requests=2, musicbrainz_timeout_seconds=.01,
        musicbrainz_base_url="https://example.test/ws/2")
    return Settings(**(defaults | values))


def recording_payload(title="Song"):
    return {"id": "123e4567-e89b-12d3-a456-426614174000", "title": title, "length": 123400,
        "artist-credit": [{"name": "Artist", "artist": {"id": "223e4567-e89b-12d3-a456-426614174000", "name": "Artist"}}],
        "isrcs": ["USABC1234567"], "releases": [{"title": "Album", "date": "2020-04",
        "release-group": {"title": "Album"}, "media": [{"position": 2, "tracks": [{"position": 3}]}]}]}


def run(value): return asyncio.run(value)


def test_normalization_exposes_domain_fields_only():
    item = normalize("recording", recording_payload())
    assert isinstance(item, RecordingCandidate)
    assert (item.artist, item.album, item.duration_seconds, item.track_number, item.disc_number) == ("Artist", "Album", 123.4, 3, 2)
    assert item.external_ids[0].namespace == "isrc"
    assert "artist-credit" not in item.model_dump()


def test_recording_normalization_exposes_release_context_for_suggestions():
    payload=recording_payload();release=payload["releases"][0]
    release.update({"id":"release-id","disambiguation":"Deluxe","artist-credit":[{"artist":{"id":"release-artist-id","name":"Album Artist"}}]})
    release["release-group"].update({"id":"group-id","first-release-date":"2019-01-01","secondary-types":["Compilation"]})
    release["media"][0]["track-count"]=10
    item=normalize("recording",payload)
    assert item.release_id=="release-id" and item.release_group_id=="group-id"
    assert item.artist_id=="223e4567-e89b-12d3-a456-426614174000" and item.release_artist_id=="release-artist-id"
    assert (item.track_number,item.total_tracks,item.disc_number,item.total_discs)==(3,10,2,1)
    assert item.original_release_date=="2019-01-01" and item.year==2020 and item.compilation is True


def test_provider_implements_abstraction():
    provider = MusicBrainzProvider(settings(), transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))
    assert isinstance(provider, MetadataProvider)
    assert "release_group" in provider.capabilities.lookup
    run(provider.close())


def test_search_pagination_and_cache_hit():
    calls = 0
    def handler(request):
        nonlocal calls; calls += 1
        assert request.url.params["offset"] == "5"
        return httpx.Response(200, json={"count": 20, "recordings": [recording_payload()]})
    provider = MusicBrainzProvider(settings(), transport=httpx.MockTransport(handler))
    first = run(provider.search("recording", "song", limit=1, offset=5))
    second = run(provider.search("recording", "song", limit=1, offset=5))
    assert first.total == 20 and first.offset == 5 and second.items[0].title == "Song" and calls == 1
    assert provider.cache.stats()["hits"] == 1
    run(provider.close())


def test_cache_bypass_and_force_refresh():
    calls = 0
    def handler(request):
        nonlocal calls; calls += 1
        return httpx.Response(200, json={"count": 1, "artists": [{"id": "123e4567-e89b-12d3-a456-426614174000", "name": f"Artist {calls}"}]})
    provider = MusicBrainzProvider(settings(), transport=httpx.MockTransport(handler))
    run(provider.search("artist", "artist"))
    bypassed = run(provider.search("artist", "artist", bypass_cache=True))
    refreshed = run(provider.search("artist", "artist", force_refresh=True))
    assert bypassed.items[0].title == "Artist 2" and refreshed.items[0].title == "Artist 3"
    assert provider.cache.stats()["bypasses"] == 2
    run(provider.close())


def test_cache_expiry_is_stale():
    provider = MusicBrainzProvider(settings(musicbrainz_cache_ttl_seconds=-1),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"count": 0, "artists": []})))
    run(provider.search("artist", "none"))
    assert provider.cache.stats()["stale_entries"] == 1
    run(provider.close())


def test_retries_transient_but_not_404():
    calls = 0
    def handler(request):
        nonlocal calls; calls += 1
        return httpx.Response(503 if calls < 3 else 200, json={"count": 0, "artists": []})
    provider = MusicBrainzProvider(settings(), transport=httpx.MockTransport(handler), sleep=lambda _: asyncio.sleep(0), random_fn=lambda: 0)
    run(provider.search("artist", "retry")); assert calls == 3
    run(provider.close())
    calls = 0
    def missing(request):
        nonlocal calls; calls += 1; return httpx.Response(404)
    provider = MusicBrainzProvider(settings(), transport=httpx.MockTransport(missing))
    with pytest.raises(ProviderError, match="HTTP 404"): run(provider.search("artist", "missing"))
    assert calls == 1
    run(provider.close())


def test_timeout_and_transport_failures_are_not_cached():
    def timeout(request): raise httpx.ReadTimeout("late", request=request)
    provider = MusicBrainzProvider(settings(musicbrainz_max_retries=0), transport=httpx.MockTransport(timeout))
    with pytest.raises(ProviderError) as error: run(provider.search("artist", "timeout"))
    assert error.value.code == "timeout"
    db = SessionLocal()
    try: assert db.query(ProviderCacheEntry).count() == 0
    finally: db.close()
    run(provider.close())


def test_malformed_response_and_validation_failure():
    provider = MusicBrainzProvider(settings(), transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"not-json")))
    with pytest.raises(ProviderError) as error: run(provider.search("artist", "bad"))
    assert error.value.code == "malformed_response"
    with pytest.raises(ProviderError) as invalid: run(provider.search("artist", ""))
    assert invalid.value.code == "validation_failure"
    run(provider.close())


def test_cancellation_interrupts_request():
    async def scenario():
        async def handler(request): await asyncio.sleep(10)
        provider = MusicBrainzProvider(settings(), transport=httpx.MockTransport(handler))
        event = asyncio.Event(); task = asyncio.create_task(provider.search("artist", "cancel", cancel_event=event))
        await asyncio.sleep(0); event.set()
        with pytest.raises(ProviderCancelledError): await task
        await provider.close()
    run(scenario())


def test_rate_limiter_is_shared_and_deterministic():
    now = [0.0]; delays = []
    async def sleep(delay): delays.append(delay); now[0] += delay
    limiter = AsyncRateLimiter(2, clock=lambda: now[0], sleep=sleep)
    async def scenario(): await asyncio.gather(limiter.acquire(), limiter.acquire(), limiter.acquire())
    run(scenario())
    assert delays == [.5, .5]


def test_concurrent_requests_are_bounded():
    active = peak = 0
    async def handler(request):
        nonlocal active, peak
        active += 1; peak = max(peak, active); await asyncio.sleep(.01); active -= 1
        return httpx.Response(200, json={"count": 0, "artists": []})
    provider = MusicBrainzProvider(settings(musicbrainz_max_concurrent_requests=2), transport=httpx.MockTransport(handler))
    async def scenario(): await asyncio.gather(*(provider.search("artist", f"q{i}") for i in range(6)))
    run(scenario()); assert peak <= 2
    run(provider.close())


def test_diagnostics_endpoints_and_page():
    client = TestClient(app)
    assert client.get("/api/providers/capabilities").status_code == 200
    status = client.get("/api/providers/status")
    assert status.status_code == 200 and "cache" in status.json()["providers"][0]
    page = client.get("/developers/providers")
    assert page.status_code == 200 and "Provider Diagnostics" in page.text
    assert client.post("/api/providers/lookup", json={"provider": "unknown", "entity_type": "artist", "entity_id": "x"}).status_code == 404
