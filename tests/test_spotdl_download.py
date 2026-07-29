import subprocess
from pathlib import Path

import pytest

from app.domain.download_outcome import DownloadFailed
from app.domain.track import Track
from app.downloaders.spotdl import AudioIdentity, SpotDLClient, validate_track_identity


@pytest.fixture
def client(monkeypatch):
    instance = SpotDLClient()
    monkeypatch.setattr("app.downloaders.spotdl.settings_service.get_settings_by_category", lambda *_: {"audio_quality": "320k"})
    monkeypatch.setattr(instance, "_read_audio_identity", lambda _: AudioIdentity("Test Title", "Test Artist", 180))
    return instance


@pytest.fixture
def track():
    return Track(artist="Test Artist", title="Test Title", duration=180,
                 spotify_url="https://open.spotify.com/track/example")


def output_dir(args):
    return Path(args[args.index("--output") + 1]).parent


def test_success_is_exactly_one_url_attempt(client, track, tmp_path, monkeypatch):
    calls = []
    def run(args, timeout):
        calls.append(args)
        (output_dir(args) / "song.mp3").write_bytes(b"audio")
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(client, "_run", run)
    assert client.download(track, tmp_path).name == "song.mp3"
    assert len(calls) == 1
    assert calls[0][0] == track.spotify_url
    assert "--dont-filter-results" not in calls[0]
    assert "Test Artist - Test Title audio" not in calls[0]


@pytest.mark.parametrize("failure", [LookupError("no match"), RuntimeError("provider failed")])
def test_execution_failure_has_no_fallback(client, track, tmp_path, monkeypatch, failure):
    calls = []
    def run(args, timeout):
        calls.append(args)
        raise failure
    monkeypatch.setattr(client, "_run", run)
    with pytest.raises(DownloadFailed):
        client.download(track, tmp_path)
    assert len(calls) == 1


def test_nonzero_and_zero_without_output_have_no_fallback(client, track, tmp_path, monkeypatch):
    for code in (1, 0):
        calls = []
        monkeypatch.setattr(client, "_run", lambda args, timeout: calls.append(args) or subprocess.CompletedProcess(args, code, "", "no match"))
        with pytest.raises(DownloadFailed) as error:
            client.download(track, tmp_path)
        assert len(calls) == 1
        assert error.value.reason_code == ("provider_no_match" if code else "exact_match_unavailable")


def test_nested_audio_and_artifact_filtering(client, track, tmp_path, monkeypatch):
    def run(args, timeout):
        directory = output_dir(args)
        nested = directory / "album" / "disc"
        nested.mkdir(parents=True)
        (nested / "song.m4a").write_bytes(b"audio")
        for name in ("metadata.json", "cover.jpg", "captions.vtt", "song.part", "song.tmp"):
            (directory / name).write_bytes(b"x")
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(client, "_run", run)
    assert client.download(track, tmp_path).name == "song.m4a"


def test_multiple_outputs_are_rejected_and_cleaned(client, track, tmp_path, monkeypatch):
    def run(args, timeout):
        (output_dir(args) / "one.mp3").write_bytes(b"x")
        (output_dir(args) / "two.flac").write_bytes(b"x")
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(client, "_run", run)
    with pytest.raises(DownloadFailed) as error:
        client.download(track, tmp_path)
    assert error.value.reason_code == "unexpected_output_count"
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("candidate", [
    AudioIdentity("test title", "TEST ARTIST", 182),
    AudioIdentity("Test—Title (Explicit)", "Test Artist", 180),
    AudioIdentity("Test Title feat. Guest", "Test Artist", 180),
])
def test_safe_identity_variations_pass(track, candidate):
    validate_track_identity(track, candidate)


@pytest.mark.parametrize("title", ["Test Title (Instrumental)", "Test Title Live", "Test Title Remix", "Test Title Karaoke", "Test Title Cover"])
def test_material_version_mismatches_fail(track, title):
    with pytest.raises(DownloadFailed):
        validate_track_identity(track, AudioIdentity(title, "Test Artist", 180))


def test_requested_remix_accepts_same_remix():
    requested = Track(title="Song (Club Remix)", artist="Artist", duration=200)
    validate_track_identity(requested, AudioIdentity("Song - Club Remix", "Artist", 202))


def test_duration_mismatch_fails(track):
    with pytest.raises(DownloadFailed):
        validate_track_identity(track, AudioIdentity("Test Title", "Test Artist", 240))


def test_confirmed_future_cut_copy_false_match_is_rejected():
    requested = Track(title="Fukk A Interview", artist="Future", duration=180)
    with pytest.raises(DownloadFailed) as error:
        validate_track_identity(requested, AudioIdentity("Future - Instrumental", "Cut Copy", 180))
    assert error.value.reason_code == "exact_match_unavailable"
