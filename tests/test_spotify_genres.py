import threading
import time

from spotipy.exceptions import SpotifyException

from app.domain.track import Track
from app.services.spotify import genres
from app.services.spotify.genres import GenreFailureCategory, _fetch_artists, enrich_tracks, normalize_genres, resolve_track_genre

A = "1" * 22
B = "2" * 22


def setup_function():
    with genres._CACHE_LOCK:
        genres._CACHE.clear(); genres._IN_FLIGHT.clear()


class Client:
    def __init__(self, responses=None, error=None): self.responses, self.error, self.calls, self.batch_calls = responses or {}, error, [], []
    def artist(self, artist_id):
        self.calls.append(artist_id)
        if self.error: raise self.error
        return self.responses.get(artist_id, {"id": artist_id, "genres": []})
    def artists(self, ids):
        self.batch_calls.append(ids)
        raise AssertionError("The removed batch endpoint must never be called")


def test_primary_artist_genres_are_selected_and_normalized():
    track = Track(spotify_artist_ids=[A, B])
    result = resolve_track_genre(track, {A: [" pop ", "POP", "indie pop"], B: ["rock"]})
    assert result.values == ["pop", "indie pop"]
    assert result.source == "primary_artist"


def test_normalize_genres_has_stable_limit():
    assert normalize_genres(["Pop", " pop ", "Rock", "Jazz"], 2) == ["Pop", "Rock"]


def test_individual_calls_are_used_for_distinct_and_duplicate_artists():
    client = Client({A: {"id": A, "genres": ["pop"]}, B: {"id": B, "genres": ["rock"]}})
    result = _fetch_artists([A, B, A], job_id=4, client_factory=lambda: client)
    assert result.artists == {A: ["pop"], B: ["rock"]}
    assert sorted(client.calls) == sorted([A, B])
    assert client.batch_calls == []


def test_cached_and_empty_successful_lookup_avoid_provider():
    client = Client({A: {"id": A, "genres": []}})
    assert _fetch_artists([A], job_id=4, client_factory=lambda: client).artists[A] == []
    assert _fetch_artists([A], job_id=4, client_factory=lambda: client).artists[A] == []
    assert client.calls == [A]


def test_spotify_403_is_classified_and_safe(caplog):
    client = Client(error=SpotifyException(403, -1, "Bearer SECRET should not appear"))
    result = _fetch_artists([A], job_id=9, client_factory=lambda: client)
    assert result.error.category == GenreFailureCategory.FORBIDDEN
    assert "SECRET" not in caplog.text
    _fetch_artists([A], job_id=9, client_factory=lambda: client)
    assert client.calls == [A]  # credential failure suppression cache


def test_401_429_network_and_malformed_ids():
    assert _fetch_artists([A], job_id=None, client_factory=lambda: Client(error=SpotifyException(401, -1, "no"))).error.category == GenreFailureCategory.UNAUTHORIZED
    assert _fetch_artists([B], job_id=None, client_factory=lambda: Client(error=SpotifyException(429, -1, "slow", headers={"Retry-After": "7"}))).error.retry_after == "7"
    assert _fetch_artists(["3" * 22], job_id=None, client_factory=lambda: Client(error=OSError("offline"))).error.category == GenreFailureCategory.NETWORK_ERROR
    assert _fetch_artists(["track-id", "x,y"], job_id=None, client_factory=lambda: Client()).artists == {}


def test_concurrent_duplicate_lookups_are_coalesced():
    class Slow(Client):
        def artist(self, artist_id): time.sleep(.05); return super().artist(artist_id)
    client = Slow({A: {"id": A, "genres": ["pop"]}})
    threads = [threading.Thread(target=lambda: _fetch_artists([A], job_id=1, client_factory=lambda: client)) for _ in range(4)]
    [thread.start() for thread in threads]; [thread.join() for thread in threads]
    assert client.calls == [A]


def test_successful_response_preserves_provenance_and_failures_are_nonfatal(monkeypatch):
    track = Track(spotify_artist_ids=[A])
    monkeypatch.setattr(genres, "_fetch_artists", lambda *args, **kwargs: genres.GenreLookupResult({A: ["pop"]}))
    enrich_tracks([track], job_id=10)
    assert track.genre == "pop" and '"provider": "spotify"' in track.genre_provenance
    failed = Track(spotify_artist_ids=[A])
    monkeypatch.setattr(genres, "_fetch_artists", lambda *args, **kwargs: genres.GenreLookupResult({}))
    enrich_tracks([failed], job_id=10)
    assert failed.genre is None
