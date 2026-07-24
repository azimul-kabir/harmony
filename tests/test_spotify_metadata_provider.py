import asyncio

import pytest

from app.core.config import Settings
from app.domain.metadata.provider import RecordingCandidate
from app.providers.metadata.errors import ProviderError
from app.providers.metadata.spotify import SpotifyMetadataProvider, normalize_recording

TRACK_ID = "1234567890123456789012"


def payload():
    return {
        "id": TRACK_ID, "name": "Signal",
        "artists": [{"id": "artist-id", "name": "Artist"}],
        "album": {"id": "album-id", "name": "Album", "artists": [{"name": "Album Artist"}],
                  "release_date": "2024-03-08", "total_tracks": 11},
        "duration_ms": 183500, "track_number": 4, "disc_number": 1,
        "external_ids": {"isrc": "USABC1234567"},
    }


class Client:
    def __init__(self): self.calls = []
    def search(self, **kwargs):
        self.calls.append(("search", kwargs))
        return {"tracks": {"items": [payload()], "total": 1}}
    def track(self, track_id):
        self.calls.append(("track", track_id))
        return payload()


def configured():
    return Settings(spotify_client_id="client", spotify_client_secret="secret")


def test_spotify_normalization_is_provider_neutral():
    item = normalize_recording(payload())
    assert isinstance(item, RecordingCandidate)
    assert (item.provider, item.title, item.artist, item.album) == ("spotify", "Signal", "Artist", "Album")
    assert (item.duration_seconds, item.track_number, item.total_tracks) == (183.5, 4, 11)
    assert item.isrc == "USABC1234567"
    assert item.release_id is None and item.artist_id is None


def test_spotify_search_and_lookup_are_bounded_recording_operations():
    client = Client()
    provider = SpotifyMetadataProvider(configured(), client_factory=lambda: client)
    page = asyncio.run(provider.search("recording", 'track:"Signal" artist:"Artist"', limit=10))
    item = asyncio.run(provider.lookup("recording", TRACK_ID))
    assert page.total == 1 and page.items[0].provider_entity_id == TRACK_ID
    assert item.provider_entity_id == TRACK_ID
    assert client.calls == [
        ("search", {"q": 'track:"Signal" artist:"Artist"', "type": "track", "limit": 10, "offset": 0}),
        ("track", TRACK_ID),
    ]
    assert provider.status()["available"] is True


def test_spotify_provider_fails_cleanly_without_credentials_or_for_other_entities():
    provider = SpotifyMetadataProvider(
        Settings(spotify_client_id=None, spotify_client_secret=None),
        client_factory=lambda: (_ for _ in ()).throw(AssertionError("client must not be created")),
    )
    with pytest.raises(ProviderError) as missing:
        asyncio.run(provider.search("recording", "Signal"))
    assert missing.value.code == "not_configured"
    configured_provider = SpotifyMetadataProvider(configured(), client_factory=Client)
    with pytest.raises(ProviderError) as unsupported:
        asyncio.run(configured_provider.search("release", "Album"))
    assert unsupported.value.code == "validation_failure"
