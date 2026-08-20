import subprocess
import signal
from pathlib import Path

import pytest

from app.domain.download_outcome import DownloadFailed
from app.domain.track import Track
from app.downloaders.spotdl import (
    AudioIdentity,
    SpotDLClient,
    SpotDLFallbackTimeout,
    validate_track_identity,
)


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
    assert "--dont-filter-results" in calls[0]
    assert "Test Artist - Test Title audio" not in calls[0]


def test_download_passes_configured_cookie_file(client, track, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        client.settings,
        "yt_dlp_cookie_file",
        "/run/secrets/youtube-cookies.txt",
    )

    def run(args, timeout):
        calls.append(args)
        (output_dir(args) / "song.mp3").write_bytes(b"audio")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(client, "_run", run)
    client.download(track, tmp_path)

    assert calls[0][calls[0].index("--cookie-file") + 1] == (
        "/run/secrets/youtube-cookies.txt"
    )


def test_attempt_log_includes_elapsed_time(client, track, tmp_path, monkeypatch):
    log_context = {}

    class BoundLogger:
        def info(self, _message, *_args):
            return None

    def bind(**context):
        log_context.update(context)
        return BoundLogger()

    monkeypatch.setattr("app.downloaders.spotdl.logger.bind", bind)
    monkeypatch.setattr("app.downloaders.spotdl.time.monotonic", lambda: 12.345)

    def run(args, timeout):
        (output_dir(args) / "song.mp3").write_bytes(b"audio")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(client, "_run", run)
    client.download(track, tmp_path, job_id=1973)

    assert log_context["job_id"] == 1973
    assert log_context["query_type"] == "spotify_url_rescue"
    assert log_context["elapsed_seconds"] == 0.0


@pytest.mark.parametrize(
    ("failure", "reason_code", "retryable"),
    [
        (LookupError("no match"), "provider_no_match", False),
        (RuntimeError("provider failed"), "provider_error", True),
    ],
)
def test_execution_failure_does_not_replay_search_ladder(
    client, track, tmp_path, monkeypatch, failure, reason_code, retryable
):
    calls = []
    def run(args, timeout):
        calls.append(args)
        raise failure
    monkeypatch.setattr(client, "_run", run)
    with pytest.raises(DownloadFailed) as error:
        client.download(track, tmp_path)
    assert len(calls) == 1
    assert error.value.reason_code == reason_code
    assert error.value.retryable is retryable


def test_nonzero_and_zero_without_output_are_terminal_no_match(client, track, tmp_path, monkeypatch):
    for code in (1, 0):
        calls = []
        monkeypatch.setattr(client, "_run", lambda args, timeout: calls.append(args) or subprocess.CompletedProcess(args, code, "", "no match"))
        with pytest.raises(DownloadFailed) as error:
            client.download(track, tmp_path)
        assert len(calls) == 1
        assert error.value.reason_code == ("provider_no_match" if code else "exact_match_unavailable")


def test_fallback_output_is_identity_validated(client, track, tmp_path, monkeypatch):
    calls = []

    def run(args, timeout):
        calls.append(args)
        (output_dir(args) / "wrong.mp3").write_bytes(b"audio")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(client, "_run", run)
    monkeypatch.setattr(
        client, "_read_audio_identity",
        lambda _: AudioIdentity("Different Song", "Different Artist", 180),
    )
    with pytest.raises(DownloadFailed) as error:
        client.download(track, tmp_path)
    assert error.value.reason_code == "exact_match_unavailable"
    assert not list(tmp_path.iterdir())


def test_single_rescue_accepts_a_controlled_less_exact_version(
    client, track, tmp_path, monkeypatch
):
    calls = []

    def run(args, timeout):
        calls.append(args)
        (output_dir(args) / "live.mp3").write_bytes(b"audio")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(client, "_run", run)
    monkeypatch.setattr(
        client,
        "_read_audio_identity",
        lambda _: AudioIdentity("Test Title Live", "Test Artist", 187),
    )

    assert client.download(track, tmp_path).name == "live.mp3"
    assert len(calls) == 1
    assert calls[0][0] == track.spotify_url
    assert "--dont-filter-results" in calls[0]


def test_loose_fallback_still_rejects_unrelated_title_from_same_artist(track):
    with pytest.raises(DownloadFailed) as error:
        validate_track_identity(
            track,
            AudioIdentity("Completely Different Song", "Test Artist", 180),
            strict=False,
        )

    assert error.value.reason_code == "fallback_match_unavailable"


def test_spotify_identity_is_preferred_over_replaying_text_searches(
    client, track, tmp_path, monkeypatch
):
    track.album = "Test Album"
    track.isrc = "USABC1234567"
    calls = []

    def run(args, timeout):
        calls.append(args)
        directory = output_dir(args)
        (directory / "rescue.mp3").write_bytes(b"audio")
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(client, "_run", run)

    selected = client.download(track, tmp_path)

    assert selected.name == "rescue.mp3"
    assert [call[0] for call in calls] == [track.spotify_url]


def test_fallback_timeout_is_typed_non_retryable_and_cleans_partial_output(
    client, track, tmp_path, monkeypatch
):
    observed = {}

    def run(args, timeout):
        observed["timeout"] = timeout
        (output_dir(args) / "partial.mp3.part").write_bytes(b"partial")
        raise SpotDLFallbackTimeout(f"SpotDL execution timed out after {timeout} seconds.")

    monkeypatch.setattr(client, "_run", run)

    with pytest.raises(DownloadFailed) as error:
        client.download(track, tmp_path, timeout_seconds=45)

    assert observed["timeout"] == 45
    assert error.value.reason_code == "spotdl_fallback_timeout"
    assert error.value.retryable is False
    assert not list(tmp_path.iterdir())


def test_run_timeout_terminates_process_group(client, tmp_path, monkeypatch):
    signals = []

    class Process:
        pid = 731
        returncode = None

        def poll(self):
            return None

        def communicate(self, timeout=None):
            if timeout == 45:
                raise subprocess.TimeoutExpired("spotdl", timeout)
            return "", ""

    monkeypatch.setenv("HARMONY_SPOTDL_CONFIG_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: Process())
    monkeypatch.setattr(
        "app.downloaders.spotdl.os.killpg",
        lambda pid, sent_signal: signals.append((pid, sent_signal)),
    )

    with pytest.raises(SpotDLFallbackTimeout):
        client._run(["track"], timeout=45)

    assert signals == [(731, signal.SIGTERM)]


def test_process_group_escalates_to_kill_when_children_do_not_exit(
    client, monkeypatch
):
    signals = []

    class Process:
        pid = 902

        def poll(self):
            return None

        def communicate(self, timeout=None):
            if timeout == 2:
                raise subprocess.TimeoutExpired("spotdl", timeout)
            return "", ""

    monkeypatch.setattr(
        "app.downloaders.spotdl.os.killpg",
        lambda pid, sent_signal: signals.append((pid, sent_signal)),
    )

    client._terminate_process_group(Process())

    assert signals == [(902, signal.SIGTERM), (902, signal.SIGKILL)]


def test_unreadable_audio_is_a_typed_identity_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.downloaders.spotdl.MutagenFile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("bad audio")),
    )
    assert SpotDLClient._read_audio_identity(tmp_path / "bad.mp3") == AudioIdentity(
        None, None, None
    )


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


@pytest.mark.parametrize(
    "candidate_title",
    ["Earned It", "Earned It [Fifty Shades Of Grey]"],
)
def test_soundtrack_qualifier_may_be_absent_or_reformatted(candidate_title):
    requested = Track(
        title="Earned It (Fifty Shades Of Grey)",
        artist="The Weeknd",
        duration=252,
    )

    validate_track_identity(
        requested, AudioIdentity(candidate_title, "The Weeknd", 252)
    )


def test_parenthetical_version_cannot_be_discarded():
    requested = Track(title="Song (Live)", artist="Artist", duration=200)

    with pytest.raises(DownloadFailed) as error:
        validate_track_identity(requested, AudioIdentity("Song", "Artist", 200))

    assert error.value.technical_detail == "title_mismatch"


@pytest.mark.parametrize("candidate_artist", [
    "The Weeknd",
    "The Weeknd; Daft Punk",
    "The Weeknd & Daft Punk",
])
def test_multi_artist_tag_representations_pass(candidate_artist):
    requested = Track(
        title="Starboy", artist="The Weeknd, Daft Punk", duration=230
    )
    validate_track_identity(
        requested, AudioIdentity("Starboy", candidate_artist, 230)
    )


def test_multi_artist_order_does_not_reject_same_recording():
    requested = Track(title="Yaaron", artist="KK", duration=269)
    validate_track_identity(
        requested,
        AudioIdentity("Yaaron", "Leslie Lewis, KK", 269),
    )


def test_album_name_may_be_appended_to_youtube_title():
    requested = Track(
        title="Mhare Hiwra Main Nache Mor",
        artist="Hariharan, Kavita Krishnamurti",
        album="Hum Saath-Saath Hain",
        duration=371,
    )
    validate_track_identity(
        requested,
        AudioIdentity(
            "Mhare Hiwra Main Nache Mor - Hum Saath Saath Hain",
            "Kavita Krishnamurti, Hariharan",
            371,
        ),
    )


def test_arbitrary_title_suffix_is_not_treated_as_album_context():
    requested = Track(
        title="Song", artist="Artist", album="Original Film", duration=200
    )
    with pytest.raises(DownloadFailed) as error:
        validate_track_identity(
            requested, AudioIdentity("Song - Different Song", "Artist", 200)
        )
    assert error.value.technical_detail == "title_mismatch"


def test_requested_artist_may_appear_after_another_primary_credit(track):
    validate_track_identity(
        track, AudioIdentity("Test Title", "Different Artist, Test Artist", 180)
    )


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


def test_legacy_millisecond_duration_passes(track):
    track.duration = 180_000
    validate_track_identity(
        track, AudioIdentity("Test Title", "Test Artist", 180)
    )


def test_confirmed_future_cut_copy_false_match_is_rejected():
    requested = Track(title="Fukk A Interview", artist="Future", duration=180)
    with pytest.raises(DownloadFailed) as error:
        validate_track_identity(requested, AudioIdentity("Future - Instrumental", "Cut Copy", 180))
    assert error.value.reason_code == "exact_match_unavailable"
