from pathlib import Path
import subprocess
import tempfile

import pytest

from app.domain.track import Track
from app.providers import youtube_music
from app.providers.youtube_music import YouTubeMusicSource, clean_title


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


def test_download_timeout_cancels_before_unregister_and_cleans_tempdir(tmp_path, monkeypatch):
    events: list[str] = []
    created: list[Path] = []
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
    monkeypatch.setattr(youtube_music.subprocess, "Popen", lambda *args, **kwargs: process)
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
