from app.services.spotify import metadata as spotify_metadata


def _track(track_id: str, name: str):
    return {
        "type": "track",
        "is_local": False,
        "id": track_id,
        "name": name,
        "artists": [{"name": "Artist"}],
        "album": {
            "id": "album-1",
            "name": "Album",
            "artists": [{"name": "Album Artist"}],
            "images": [{"url": "https://example.com/cover.jpg"}],
            "release_date": "2026-01-01",
        },
        "track_number": 1,
        "disc_number": 1,
        "duration_ms": 123000,
        "external_urls": {
            "spotify": f"https://open.spotify.com/track/{track_id}",
        },
        "external_ids": {
            "isrc": f"ISRC-{track_id}",
        },
    }


class FakeSpotify:
    def __init__(self):
        self.next_calls = 0
        self.second_page = {
            "items": [
                {"track": _track("track-2", "Second Song")},
                {"track": {"type": "episode", "is_local": False}},
                {"track": {"type": "track", "is_local": True}},
            ],
            "next": None,
        }

    def playlist(self, playlist_id: str):
        assert playlist_id == "playlist-1"

        return {
            "name": "Road Trip",
            "external_urls": {
                "spotify": "https://open.spotify.com/playlist/playlist-1",
            },
            "tracks": {
                "items": [
                    {"track": _track("track-1", "First Song")},
                ],
                "next": "https://api.spotify.com/v1/playlists/playlist-1/tracks?offset=1",
            },
        }

    def next(self, page):
        self.next_calls += 1
        return self.second_page


def test_resolve_playlist_details_paginates_and_keeps_track_urls(monkeypatch):
    fake_spotify = FakeSpotify()

    monkeypatch.setattr(
        spotify_metadata,
        "get_client",
        lambda: fake_spotify,
    )

    playlist = spotify_metadata.resolve_playlist_details(
        "https://open.spotify.com/playlist/playlist-1?si=abc123"
    )

    assert playlist.name == "Road Trip"
    assert playlist.track_count == 2
    assert fake_spotify.next_calls == 1
    assert [track.title for track in playlist.tracks] == [
        "First Song",
        "Second Song",
    ]
    assert playlist.tracks[0].spotify_url == "https://open.spotify.com/track/track-1"
    assert playlist.tracks[1].spotify_url == "https://open.spotify.com/track/track-2"
