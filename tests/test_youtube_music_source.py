from pathlib import Path
from io import BytesIO
import subprocess
import tempfile

import pytest
from mutagen.id3 import ID3
from PIL import Image

from app.domain.track import Track
from app.providers import youtube_music
from app.providers.youtube_music import (
    YouTubeMusicSource,
    _best_artwork,
    _download_artwork_url,
    _fetch_artwork,
    _square_jpeg,
    _yt_dlp_command,
    _youtube_music_artwork,
    _youtube_music_track,
    _write_download_tags,
    clean_title,
)


def test_yt_dlp_command_enables_discovered_deno(monkeypatch):
    monkeypatch.setattr(
        youtube_music.shutil,
        "which",
        lambda name: "/opt/deno/bin/deno" if name == "deno" else None,
    )

    assert _yt_dlp_command("yt-dlp") == [
        "yt-dlp",
        "--js-runtimes",
        "deno:/opt/deno/bin/deno",
    ]


def test_detects_public_youtube_music_and_standard_fallback_urls():
    source = YouTubeMusicSource()
    assert source.detect_url("https://music.youtube.com/watch?v=abc1234") == ("track", "abc1234")
    assert source.detect_url("music.youtube.com/watch?v=abc1234") == ("track", "abc1234")
    assert source.detect_url("https://music.youtube.com/playlist?list=PLabc") == ("playlist", "PLabc")
    assert source.detect_url("https://www.youtube.com/watch?v=abc1234") == ("track", "abc1234")
    assert source.detect_url("https://www.youtube.com/channel/channel") is None


def test_resolve_keeps_youtube_music_watch_url(monkeypatch):
    source = YouTubeMusicSource()
    targets: list[str] = []

    def run_json(target, *, flat=False):
        targets.append(target)
        return {"id": "abc1234", "title": "Song", "uploader": "Artist"}

    monkeypatch.setattr(source, "_run_json", run_json)
    monkeypatch.setattr(youtube_music, "_youtube_music_track", lambda _item_id: {})
    tracks = source.resolve("music.youtube.com/watch?v=abc1234")

    assert targets == ["https://www.youtube.com/watch?v=abc1234"]
    assert tracks[0].source_url == "https://music.youtube.com/watch?v=abc1234"


def test_resolve_preserves_standard_youtube_fallback_url(monkeypatch):
    source = YouTubeMusicSource()
    targets: list[str] = []

    def run_json(target, *, flat=False):
        targets.append(target)
        return {"id": "abc1234", "title": "Song", "uploader": "Artist"}

    monkeypatch.setattr(source, "_run_json", run_json)
    monkeypatch.setattr(youtube_music, "_youtube_music_track", lambda _item_id: {})
    tracks = source.resolve("https://www.youtube.com/watch?v=abc1234")

    assert targets == ["https://www.youtube.com/watch?v=abc1234"]
    assert tracks[0].source_url == "https://www.youtube.com/watch?v=abc1234"


def test_metadata_cleanup_only_removes_known_presentation_suffixes():
    assert clean_title("Song (Official Audio)") == "Song"
    assert clean_title("Song (Live at Home)") == "Song (Live at Home)"


def test_artwork_selection_prioritizes_square_album_cover():
    data = {"thumbnails": [
        {"url": "https://example/wide.jpg", "width": 1920, "height": 1080},
        {"url": "https://example/cover.jpg", "width": 544, "height": 544},
    ]}
    assert _best_artwork(data) == "https://example/cover.jpg"


def test_artwork_selection_accepts_youtube_music_thumbnail_shape():
    data = {"thumbnail": [
        {"url": "https://example/cover-60.jpg", "width": 60, "height": 60},
        {"url": "https://example/cover-544.jpg", "width": 544, "height": 544},
    ]}
    assert _best_artwork(data) == "https://example/cover-544.jpg"


def test_youtube_music_track_matches_video_counterpart(monkeypatch):
    class Client:
        def get_watch_playlist(self, **kwargs):
            assert kwargs == {"videoId": "video123", "limit": 1}
            return {"tracks": [
                {"videoId": "audio123", "counterpart": {"videoId": "video123"}, "thumbnail": []},
            ]}

    monkeypatch.setattr(youtube_music, "YTMusic", Client)
    assert _youtube_music_track("video123")["videoId"] == "audio123"


def test_youtube_music_artwork_uses_album_endpoint_instead_of_video_preview(monkeypatch):
    class Client:
        def get_watch_playlist(self, **kwargs):
            assert kwargs == {"videoId": "video123", "limit": 1}
            return {"tracks": [{
                "videoId": "video123",
                "album": {"id": "album123"},
                "thumbnail": [{
                    "url": "https://i.ytimg.com/vi/video123/hq720.jpg",
                    "width": 1280,
                    "height": 720,
                }],
            }]}

        def get_album(self, album_id):
            assert album_id == "album123"
            return {"thumbnails": [{
                "url": "https://lh3.googleusercontent.com/album-cover",
                "width": 544,
                "height": 544,
            }]}

    monkeypatch.setattr(youtube_music, "YTMusic", Client)

    assert _youtube_music_artwork("video123") == "https://lh3.googleusercontent.com/album-cover"


def test_youtube_music_artwork_does_not_return_video_preview(monkeypatch):
    class Client:
        def get_watch_playlist(self, **_kwargs):
            return {"tracks": [{
                "videoId": "video123",
                "thumbnail": [{"url": "https://i.ytimg.com/vi/video123/hq720.jpg"}],
            }]}

    monkeypatch.setattr(youtube_music, "YTMusic", Client)

    assert _youtube_music_artwork("video123") is None


def test_result_uses_music_album_art_instead_of_video_thumbnail(monkeypatch):
    monkeypatch.setattr(youtube_music, "_youtube_music_track", lambda _item_id: {
        "thumbnail": [{"url": "https://lh3.googleusercontent.com/album", "width": 544, "height": 544}],
    })
    result = YouTubeMusicSource()._result({
        "id": "video123",
        "title": "Song",
        "thumbnail": "https://i.ytimg.com/video-preview.jpg",
    })
    assert result.artwork_url == "https://lh3.googleusercontent.com/album"


def test_result_prefers_canonical_youtube_music_metadata(monkeypatch):
    monkeypatch.setattr(youtube_music, "_youtube_music_track", lambda _item_id: {
        "title": "Canonical Song",
        "artists": [{"name": "Primary Artist"}, {"name": "Guest Artist"}],
        "album": {"name": "Canonical Album", "id": "album123"},
        "duration_seconds": 243,
        "isExplicit": True,
    })

    result = YouTubeMusicSource()._result({
        "id": "video123",
        "title": "Video title (Official Video)",
        "uploader": "Uploader - Topic",
        "album": "Imported Playlist Name",
    })

    assert result.title == "Canonical Song"
    assert result.artist == "Primary Artist, Guest Artist"
    assert result.album == "Canonical Album"
    assert result.album_artist == "Primary Artist"
    assert result.duration == 243
    assert result.explicit is True


def test_playlist_name_is_never_used_as_track_album(monkeypatch):
    source = YouTubeMusicSource()
    targets: list[tuple[str, bool]] = []
    playlist = {
        "title": "My Playlist",
        "entries": [{"id": "video123", "title": "Flat title"}],
    }
    hydrated = {"id": "video123", "title": "Hydrated title"}
    def run_json(target, *, flat=False):
        targets.append((target, flat))
        return playlist if flat else hydrated

    monkeypatch.setattr(source, "_run_json", run_json)
    monkeypatch.setattr(youtube_music, "_youtube_music_track", lambda _item_id: {})

    resolved = source.resolve("https://music.youtube.com/playlist?list=PLabc")

    assert resolved[0].album == "Singles"
    assert resolved[0].track is None
    assert targets == [
        ("https://music.youtube.com/playlist?list=PLabc", True),
        ("https://www.youtube.com/watch?v=video123", False),
    ]


def test_synced_playlist_track_resolves_album_art_when_download_starts(monkeypatch):
    monkeypatch.setattr(youtube_music, "_youtube_music_track", lambda item_id: {
        "videoId": item_id,
        "thumbnail": [
            {"url": "https://lh3.googleusercontent.com/cover-60", "width": 60, "height": 60},
            {"url": "https://lh3.googleusercontent.com/cover-544", "width": 544, "height": 544},
        ],
    })
    track = Track(
        source_provider="youtube_music",
        source_item_id="video123",
        source_url="https://music.youtube.com/watch?v=video123",
    )

    assert _download_artwork_url(track) == "https://lh3.googleusercontent.com/cover-544"


def test_download_artwork_resolution_preserves_queued_cover(monkeypatch):
    def unexpected_lookup(_item_id):
        raise AssertionError("canonical metadata should not be fetched")

    monkeypatch.setattr(youtube_music, "_youtube_music_track", unexpected_lookup)
    track = Track(cover_url="https://images.example/queued-cover.jpg")

    assert _download_artwork_url(track) == "https://images.example/queued-cover.jpg"


def test_artwork_is_center_cropped_to_square_and_bounded():
    source = BytesIO()
    Image.new("RGB", (2400, 1200), "red").save(source, "PNG")
    artwork = _square_jpeg(source.getvalue())
    with Image.open(BytesIO(artwork)) as image:
        assert image.size == (1200, 1200)
        assert image.format == "JPEG"


def test_video_preview_is_rejected_as_album_art():
    with pytest.raises(ValueError, match="video previews"):
        _fetch_artwork("https://i.ytimg.com/vi/video123/hqdefault.jpg")


def test_download_tags_include_album_artist_hierarchy_and_source(tmp_path):
    path = tmp_path / "track.mp3"
    path.write_bytes(b"audio placeholder")
    track = Track(
        title="Song", artist="Guest Artist", album_artist="Album Artist",
        album="Album", track=3, disc=1, year=2024, genre="Rock", isrc="USABC2400001",
        source_item_id="abc1234", source_url="https://www.youtube.com/watch?v=abc1234",
    )
    _write_download_tags(path, track, {}, None)
    tags = ID3(path)
    assert str(tags["TIT2"]) == "Song"
    assert str(tags["TPE1"]) == "Guest Artist"
    assert str(tags["TPE2"]) == "Album Artist"
    assert str(tags["TALB"]) == "Album"
    assert str(tags["TRCK"]) == "3"
    assert str(tags["TPOS"]) == "1"
    assert str(tags["TDRC"]) == "2024"
    assert str(tags["TCON"]) == "Rock"
    assert str(tags["TSRC"]) == "USABC2400001"
    assert tags.getall("TXXX:YouTube Music ID")[0].text == ["abc1234"]


def test_download_timeout_cancels_before_unregister_and_cleans_tempdir(tmp_path, monkeypatch):
    events: list[str] = []
    created: list[Path] = []
    commands: list[list[str]] = []
    real_temporary_directory = tempfile.TemporaryDirectory

    class RecordingTemporaryDirectory(real_temporary_directory):
        def __enter__(self):
            path = Path(super().__enter__())
            created.append(path)
            return str(path)

    class TimedOutProcess:
        pid = 123
        returncode = None
        def communicate(self, timeout):
            events.append("communicate")
            raise subprocess.TimeoutExpired("yt-dlp", timeout)

    process = TimedOutProcess()
    monkeypatch.setattr(youtube_music.tempfile, "TemporaryDirectory", RecordingTemporaryDirectory)
    monkeypatch.setattr(
        youtube_music.subprocess,
        "Popen",
        lambda command, **kwargs: commands.append(command) or process,
    )
    monkeypatch.setattr(youtube_music.download_processes, "register", lambda job_id, value: events.append("register") or True)
    def cancel(job_id):
        assert events == ["register", "communicate"]
        events.append("cancel")
        return True
    monkeypatch.setattr(youtube_music.download_processes, "cancel", cancel)
    monkeypatch.setattr(youtube_music.download_processes, "unregister", lambda job_id, value: events.append("unregister"))
    track = Track(source_provider="youtube_music", source_url="https://music.youtube.com/watch?v=abc1234")
    with pytest.raises(ValueError, match="^YouTube Music download timed out\\.$") as error:
        YouTubeMusicSource().download(track, str(tmp_path), job_id=9)
    assert "123" not in str(error.value)
    assert events == ["register", "communicate", "cancel", "unregister"]
    assert len(created) == 1 and not created[0].exists()
    assert "--write-info-json" in commands[0]
    assert "--write-thumbnail" not in commands[0]
    assert "--embed-thumbnail" not in commands[0]
    assert "--convert-thumbnails" not in commands[0]
    assert commands[0][-1] == "https://www.youtube.com/watch?v=abc1234"


def test_download_preserves_standard_youtube_fallback_endpoint(tmp_path, monkeypatch):
    commands: list[list[str]] = []

    class FailedProcess:
        pid = 123
        returncode = 1

        def communicate(self, timeout):
            return "", "video unavailable"

    monkeypatch.setattr(
        youtube_music.subprocess,
        "Popen",
        lambda command, **kwargs: commands.append(command) or FailedProcess(),
    )
    monkeypatch.setattr(youtube_music.download_processes, "register", lambda *_args: True)
    monkeypatch.setattr(youtube_music.download_processes, "unregister", lambda *_args: None)
    track = Track(
        source_provider="youtube_music",
        source_url="https://www.youtube.com/watch?v=abc1234",
    )

    with pytest.raises(ValueError, match="could not download"):
        YouTubeMusicSource().download(track, str(tmp_path), job_id=9)

    assert commands[0][-1] == "https://www.youtube.com/watch?v=abc1234"
