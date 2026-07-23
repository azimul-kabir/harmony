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
    assert source.detect_url("https://music.youtube.com/playlist?list=PLabc") == ("playlist", "PLabc")
    assert source.detect_url("https://www.youtube.com/watch?v=abc1234") == ("track", "abc1234")
    assert source.detect_url("https://www.youtube.com/channel/channel") is None


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


def test_download_retries_without_square_artwork_when_thumbnail_conversion_fails(tmp_path, monkeypatch):
    commands: list[list[str]] = []

    class DummySession:
        def close(self):
            pass

    class ThumbnailFailureProcess:
        pid = 101
        returncode = 1

        def communicate(self, timeout):
            return "", "ERROR: thumbnail conversion failed"

    class SuccessfulProcess:
        pid = 102
        returncode = 0

        def communicate(self, timeout):
            template = commands[-1][commands[-1].index("-o") + 1]
            Path(template.replace("%(title)s.%(ext)s", "song.mp3")).write_bytes(b"audio")
            return "", ""

    processes = iter([ThumbnailFailureProcess(), SuccessfulProcess()])

    def popen(command, **kwargs):
        commands.append(command)
        return next(processes)

    monkeypatch.setattr(youtube_music, "SessionLocal", DummySession)
    monkeypatch.setattr(youtube_music.settings_service, "get_settings_by_category", lambda db, category: {"audio_quality": "192k"})
    monkeypatch.setattr(youtube_music.subprocess, "Popen", popen)
    monkeypatch.setattr(youtube_music.download_processes, "register", lambda job_id, process: True)
    monkeypatch.setattr(youtube_music.download_processes, "unregister", lambda job_id, process: None)

    track = Track(source_provider="youtube_music", source_url="https://music.youtube.com/watch?v=abc1234")
    output = YouTubeMusicSource().download(track, str(tmp_path), job_id=9)

    assert output.exists()
    assert "--convert-thumbnails" in commands[0]
    assert "--convert-thumbnails" not in commands[1]
    assert commands[0][commands[0].index("--audio-quality") + 1] == "192k"


def test_global_download_script_uses_a_versioned_url():
    template = Path("app/templates/base.html").read_text()
    assert '/static/js/app.js?v={{ app_js_version }}' in template
