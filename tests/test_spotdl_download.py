import subprocess
from pathlib import Path

import pytest

from app.domain.track import Track
from app.downloaders.spotdl import SpotDLClient


@pytest.fixture
def client(monkeypatch):
    instance = SpotDLClient()
    monkeypatch.setattr(
        "app.downloaders.spotdl.settings_service.get_settings_by_category",
        lambda _db, _category: {"audio_quality": "320k"},
    )
    return instance


@pytest.fixture
def track():
    return Track(
        artist="Test Artist",
        title="Test Title",
        spotify_url="https://open.spotify.com/track/example",
    )


def _output_directory(args: list[str]) -> Path:
    template = Path(args[args.index("--output") + 1])
    return template.parent


def test_no_output_from_spotify_url_uses_loose_fallback(client, track, tmp_path, monkeypatch):
    calls = []

    def run(args, timeout):
        calls.append(args)
        if len(calls) == 1:
            return subprocess.CompletedProcess(args, 0, "https://music.youtube.com/watch?v=abc", "")
        (_output_directory(args) / "fallback.mp3").write_bytes(b"audio")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(client, "_run", run)

    result = client.download(track, tmp_path)

    assert result.name == "fallback.mp3"
    assert len(calls) == 2
    assert "--dont-filter-results" not in calls[0]
    assert "--dont-filter-results" in calls[1]


def test_lookup_error_from_spotify_url_uses_loose_fallback(client, track, tmp_path, monkeypatch):
    calls = []

    def run(args, timeout):
        calls.append(args)
        if len(calls) == 1:
            raise LookupError("No match for Spotify metadata")
        (_output_directory(args) / "fallback.flac").write_bytes(b"audio")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(client, "_run", run)

    assert client.download(track, tmp_path).name == "fallback.flac"
    assert len(calls) == 2


def test_nested_audio_output_is_discovered_without_fallback(client, track, tmp_path, monkeypatch):
    calls = []

    def run(args, timeout):
        calls.append(args)
        nested = _output_directory(args) / "album" / "disc"
        nested.mkdir(parents=True)
        (nested / "song.m4a").write_bytes(b"audio")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(client, "_run", run)

    assert client.download(track, tmp_path).name == "song.m4a"
    assert len(calls) == 1


def test_youtube_url_only_is_reported_as_zero_exit_without_output(client, track, tmp_path, monkeypatch):
    monkeypatch.setattr(
        client,
        "_run",
        lambda args, timeout: subprocess.CompletedProcess(
            args, 0, "https://music.youtube.com/watch?v=qNp-HoFiE4A", ""
        ),
    )

    with pytest.raises(RuntimeError) as exc_info:
        client.download(track, tmp_path)

    message = str(exc_info.value)
    assert "2 attempts (spotify_url, loose_search)" in message
    assert "SpotDL returned zero with no output" in message
    assert "SpotDL completed without producing an output file" in message
    assert "qNp-HoFiE4A" not in message


def test_final_error_uses_bounded_meaningful_diagnostic(client, track, tmp_path, monkeypatch):
    diagnostic = "AudioProviderError: YT-DLP failed with 403 " + ("detail " * 200)
    monkeypatch.setattr(
        client,
        "_run",
        lambda args, timeout: subprocess.CompletedProcess(args, 1, "matched URL", diagnostic),
    )

    with pytest.raises(RuntimeError) as exc_info:
        client.download(track, tmp_path)

    message = str(exc_info.value)
    assert "Test Artist - Test Title" in message
    assert "SpotDL returned nonzero (1)" in message
    assert "AudioProviderError" in message
    assert len(message) < 800


def test_non_audio_artifacts_do_not_count_as_download(client, track, tmp_path, monkeypatch):
    calls = []

    def run(args, timeout):
        calls.append(args)
        directory = _output_directory(args)
        (directory / "metadata.json").write_text("{}")
        (directory / "cover.jpg").write_bytes(b"image")
        (directory / "captions.vtt").write_text("captions")
        if len(calls) == 2:
            (directory / "song.opus").write_bytes(b"audio")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(client, "_run", run)

    assert client.download(track, tmp_path).name == "song.opus"
    assert len(calls) == 2


def test_successful_first_attempt_does_not_execute_fallback(client, track, tmp_path, monkeypatch):
    calls = []

    def run(args, timeout):
        calls.append(args)
        (_output_directory(args) / "song.mp3").write_bytes(b"audio")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(client, "_run", run)

    client.download(track, tmp_path)
    assert len(calls) == 1

