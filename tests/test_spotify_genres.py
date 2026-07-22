from app.domain.track import Track
from app.services.spotify.genres import normalize_genres, resolve_track_genre


def test_primary_artist_genres_are_selected_and_normalized(monkeypatch):
    track = Track(spotify_artist_ids=["primary", "featured"])
    result = resolve_track_genre(track, {"primary": [" pop ", "POP", "indie pop"], "featured": ["rock"]})
    assert result.values == ["pop", "indie pop"]
    assert result.source == "primary_artist"
    assert not result.fallback


def test_featured_artist_is_only_a_fallback():
    track = Track(spotify_artist_ids=["primary", "featured"])
    result = resolve_track_genre(track, {"primary": [], "featured": ["rock"]})
    assert result.values == ["rock"]
    assert result.fallback


def test_normalize_genres_has_stable_limit():
    assert normalize_genres(["Pop", " pop ", "Rock", "Jazz"], 2) == ["Pop", "Rock"]
