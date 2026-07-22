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


def test_primary_artist_genres_are_selected_and_normalized():
    track = Track(spotify_artist_ids=[A, B])
    result = resolve_track_genre(track, {A: [" pop ", "POP", "indie pop"], B: ["rock"]})
    assert result.values == ["pop", "indie pop"]
    assert result.source == "primary_artist"
    assert not result.fallback


def test_featured_artist_is_only_a_fallback():
    track = Track(spotify_artist_ids=[A, B])
    assert resolve_track_genre(track, {A: [], B: ["rock"]}).fallback


def test_normalize_genres_has_stable_limit():
    assert normalize_genres(["Pop", " pop ", "Rock", "Jazz"], 2) == ["Pop", "Rock"]


class Client:
    def __init__(self, response=None, error=None): self.response, self.error, self.calls = response, error, []
    def artists(self, ids):
        self.calls.append(ids)
        if self.error: raise self.error
        return self.response


def test_successful_single_and_cached_lookup():
    client = Client({"artists": [{"id": A, "genres": ["pop"]}]})
    assert _fetch_artists([A], job_id=4, client_factory=lambda: client).artists[A] == ["pop"]
    assert _fetch_artists([A], job_id=4, client_factory=lambda: client).artists[A] == ["pop"]
    assert client.calls == [[A]]


def test_batched_multi_artist_and_duplicates_are_fetched_once():
    ids = [f"{i:022d}" for i in range(51)]
    client = Client({"artists": [{"id": artist_id, "genres": []} for artist_id in ids]})
    _fetch_artists(ids + [ids[0]], job_id=None, client_factory=lambda: client)
    assert [len(batch) for batch in client.calls] == [50, 1]


def test_spotify_failures_are_classified_and_safe(caplog):
    client = Client(error=SpotifyException(429, -1, "Bearer SECRET should not appear", headers={"Retry-After": "7"}))
    result = _fetch_artists([A], job_id=9, client_factory=lambda: client)
    assert result.error.category == GenreFailureCategory.RATE_LIMITED
    assert result.error.retry_after == "7"
    assert "SECRET" not in caplog.text
    assert _fetch_artists([A], job_id=9, client_factory=lambda: client).artists[A] == []


def test_401_network_empty_and_malformed_ids():
    unauthorized = _fetch_artists([A], job_id=None, client_factory=lambda: Client(error=SpotifyException(401, -1, "no")))
    assert unauthorized.error.category == GenreFailureCategory.UNAUTHORIZED
    network = _fetch_artists([B], job_id=None, client_factory=lambda: Client(error=OSError("offline")))
    assert network.error.category == GenreFailureCategory.NETWORK_ERROR
    empty = _fetch_artists(["3" * 22], job_id=None, client_factory=lambda: Client({"artists": [{"id": "3" * 22, "genres": []}]}))
    assert empty.artists["3" * 22] == []
    assert _fetch_artists(["track-id", "x,y"], job_id=None, client_factory=lambda: Client()).artists == {}


def test_concurrent_requests_do_not_duplicate_provider_call():
    class Slow(Client):
        def artists(self, ids):
            time.sleep(.05); return super().artists(ids)
    client = Slow({"artists": [{"id": A, "genres": ["pop"]}]})
    threads = [threading.Thread(target=lambda: _fetch_artists([A], job_id=1, client_factory=lambda: client)) for _ in range(4)]
    [thread.start() for thread in threads]; [thread.join() for thread in threads]
    assert len(client.calls) == 1


def test_enrichment_failure_does_not_change_existing_genre(monkeypatch):
    track = Track(spotify_artist_ids=[A], genre="User genre")
    monkeypatch.setattr(genres, "_fetch_artists", lambda *args, **kwargs: genres.GenreLookupResult({}))
    enrich_tracks([track], job_id=10)
    assert track.genre == "User genre"
