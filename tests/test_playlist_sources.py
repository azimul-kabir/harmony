from types import SimpleNamespace

import pytest

from app.api.sync_sources import create_playlist_source
from app.database.models import Playlist, PlaylistTrack, SyncSource
from app.database.session import SessionLocal
from app.domain.track import Track
from app.services import playlist_sync
from app.services.playlist_source import PlaylistSourceError, parse_playlist_source


YTM_ID = "RDCLAK5uy_n1yUj1SIY2iIAIiVtdlwy6z7RLFqKXmB0"


@pytest.mark.parametrize("url", [
    f"https://music.youtube.com/playlist?list={YTM_ID}&playnext=1&si=example",
    f"music.youtube.com/playlist?list={YTM_ID}",
])
def test_youtube_music_playlist_parser_canonicalizes(url):
    parsed = parse_playlist_source(url)
    assert parsed.provider == "youtube_music"
    assert parsed.external_id == YTM_ID
    assert parsed.canonical_url == f"https://music.youtube.com/playlist?list={YTM_ID}"


def test_spotify_playlist_parser_accepts_url_and_uri():
    expected = "https://open.spotify.com/playlist/abc123"
    assert parse_playlist_source(expected).canonical_url == expected
    assert parse_playlist_source("spotify:playlist:abc123").canonical_url == expected


@pytest.mark.parametrize("url", [
    "https://music.youtube.com/watch?v=abcdefgh",
    "https://example.com/playlist/abc",
    "https://music.youtube.com/playlist?list=bad!",
])
def test_playlist_parser_rejects_non_playlist_and_unsupported_urls(url):
    with pytest.raises(PlaylistSourceError):
        parse_playlist_source(url)


def test_source_creation_is_provider_aware_and_deduplicates_canonical_urls():
    with SessionLocal() as db:
        first = create_playlist_source(db, f"https://music.youtube.com/playlist?list={YTM_ID}&si=one")
        duplicate = create_playlist_source(db, f"music.youtube.com/playlist?list={YTM_ID}&playnext=1")
        spotify = create_playlist_source(db, f"https://open.spotify.com/playlist/{YTM_ID}")
        assert duplicate.id == first.id
        assert first.provider == "youtube_music"
        assert first.external_id == YTM_ID
        assert spotify.id != first.id


def test_youtube_music_sync_dispatches_and_preserves_order(monkeypatch):
    with SessionLocal() as db:
        source = SyncSource(type="playlist", provider="youtube_music", external_id=YTM_ID,
            source_url=f"https://music.youtube.com/playlist?list={YTM_ID}",
            spotify_id=f"youtube_music:{YTM_ID}", spotify_url=f"https://music.youtube.com/playlist?list={YTM_ID}",
            name="Fetching Playlist Data...")
        db.add(source); db.commit(); db.refresh(source)
        used = []

        class Reader:
            skipped_count = 1
            def __init__(self, url): used.append(url)
            def metadata(self): return SimpleNamespace(name="Public mix")
            def batches(self):
                yield [Track(title="One", artist="Artist", source_provider="youtube_music", source_item_id="video1", source_url="https://music.youtube.com/watch?v=video1"),
                       Track(title="Two", artist="Artist", source_provider="youtube_music", source_item_id="video2", source_url="https://music.youtube.com/watch?v=video2")]

        monkeypatch.setattr(playlist_sync, "YouTubeMusicPlaylistReader", Reader)
        monkeypatch.setattr(playlist_sync, "_can_enqueue", lambda **_: True)
        monkeypatch.setattr(playlist_sync, "enqueue_tracks_bulk", lambda *_: None)
        monkeypatch.setattr(playlist_sync, "export_m3u", lambda *_args, **_kwargs: 0)
        task = playlist_sync.sync_playlist(db, source)
        playlist = db.query(Playlist).filter_by(source_provider="youtube_music", source_external_id=YTM_ID).one()
        tracks = db.query(PlaylistTrack).filter_by(playlist_id=playlist.id).order_by(PlaylistTrack.position).all()
        assert used and source.name == "Public mix"
        assert [track.spotify_track_id for track in tracks] == ["youtube_music:video1", "youtube_music:video2"]
        assert task.skipped_items == 1
