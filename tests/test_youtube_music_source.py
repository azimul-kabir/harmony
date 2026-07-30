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
    _square_jpeg,
    _write_download_tags,
    clean_title,
)


def test_detects_public_youtube_music_and_standard_fallback_urls():
    source = YouTubeMusicSource()
    assert source.detect_url("https://music.youtube.com/watch?v=abc1234") == ("track", "abc1234")
    assert source.detect_url("music.youtube.com/watch?v=abc1234") == ("track", "abc1234")
    assert source.detect_url("https://music.youtube.com/playlist?list=PLabc") == ("playlist", "PLabc")
    assert source.detect_url("https://www.youtube.com/watch?v=abc1234") == ("track", "abc1234")
    assert source.detect_url("https://www.youtube.com/channel/channel") is None


def test_resolve_uses_regular_watch_url_for_youtube_music_track(monkeypatch):
    source = YouTubeMusicSource()
    targets: list[str] = []

    def run_json(target, *, flat=False):
        targets.append(target)
        return {"id": "abc1234", "title": "Song", "uploader": "Artist"}

    monkeypatch.setattr(source, "_run_json", run_json)
    tracks = source.resolve("music.youtube.com/watch?v=abc1234")

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


def test_artwork_is_center_cropped_to_square_and_bounded():
    source = BytesIO()
    Image.new("RGB", (2400, 1200), "red").save(source, "PNG")
    artwork = _square_jpeg(source.getvalue())
    with Image.open(BytesIO(artwork)) as image:
        assert image.size == (1200, 1200)
        assert image.format == "JPEG"


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
    assert "--write-thumbnail" in commands[0]
    assert "--embed-thumbnail" not in commands[0]
    assert commands[0][commands[0].index("--convert-thumbnails") + 1] == "jpg"
