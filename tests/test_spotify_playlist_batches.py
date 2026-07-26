from importlib.metadata import version

import pytest

from app.services.spotify import playlist_batches


def _raw_track(number):
    return {
        "itemV3": {
            "data": {
                "uri": f"spotify:track:id-{number}",
                "identityTrait": {
                    "name": f"Song {number}",
                    "description": "",
                    "contributors": {"items": [{"name": "Artist"}]},
                },
            }
        },
        "itemV2": {
            "data": {
                "mediaType": "AUDIO",
                "uri": f"spotify:track:id-{number}",
                "trackDuration": {"totalMilliseconds": 180000},
                "discNumber": 1,
                "trackNumber": number,
                "contentRating": {"label": "NONE"},
            }
        },
    }


def test_unofficial_reader_rebatches_provider_pages(monkeypatch):
    class Provider:
        def __init__(self, playlist_id):
            assert playlist_id == "playlist-id"

        def paginate_playlist(self):
            yield {"items": [_raw_track(number) for number in range(1, 44)]}
            yield {"items": [_raw_track(number) for number in range(44, 53)]}

    monkeypatch.setattr(playlist_batches, "PublicPlaylist", Provider)
    monkeypatch.setattr(playlist_batches, "_check_compatibility", lambda: None)
    reader = playlist_batches.UnofficialSpotifyPlaylistReader(
        "https://open.spotify.com/playlist/playlist-id",
        batch_size=50,
    )

    batches = list(reader.batches())

    assert [len(batch) for batch in batches] == [50, 2]
    assert batches[0][0].spotify_track_id == "id-1"
    assert batches[1][-1].spotify_url.endswith("id-52")


def test_reader_rejects_non_playlist_url():
    with pytest.raises(ValueError, match="public Spotify playlist"):
        playlist_batches.UnofficialSpotifyPlaylistReader(
            "https://open.spotify.com/track/not-a-playlist"
        )


def test_spotdl_internal_api_version_is_pinned():
    assert version("spotdl") == playlist_batches.SUPPORTED_SPOTDL_VERSION
