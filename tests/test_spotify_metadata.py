from app.services.spotify.metadata import _track_from_spotify, resolve_album


def spotify_track(*, nested_album=True):
    item = {
        "id": "track-id",
        "name": "Starboy",
        "artists": [{"id": "weeknd-id", "name": "The Weeknd"}],
        "duration_ms": 230_453,
        "track_number": 1,
        "disc_number": 1,
        "external_urls": {"spotify": "https://open.spotify.com/track/track-id"},
        "external_ids": {"isrc": "USUG11600976"},
    }
    if nested_album:
        item["album"] = {
            "id": "album-id",
            "name": "Starboy",
            "artists": [{"name": "The Weeknd"}],
            "release_date": "2016-11-25",
            "images": [{"url": "https://example.test/cover.jpg"}],
        }
    return item


def test_track_metadata_converts_spotify_milliseconds_to_seconds():
    track = _track_from_spotify(spotify_track())
    assert track.duration == 230.453


def test_album_metadata_converts_spotify_milliseconds_to_seconds(monkeypatch):
    album = {
        "id": "album-id",
        "name": "Starboy",
        "artists": [{"name": "The Weeknd"}],
        "release_date": "2016-11-25",
        "images": [{"url": "https://example.test/cover.jpg"}],
        "tracks": {"items": [spotify_track(nested_album=False)]},
    }

    class Spotify:
        def album(self, _album_id):
            return album

    monkeypatch.setattr("app.services.spotify.metadata.get_client", Spotify)
    tracks = resolve_album("https://open.spotify.com/album/album-id")
    assert tracks[0].duration == 230.453
