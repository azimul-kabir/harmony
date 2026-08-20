from pathlib import Path

import pytest

from app.domain.download_outcome import DownloadFailed
from app.domain.track import Track
from app.providers.download_source import SourceResult
from app.services import download
from app.services.direct_acquisition import DirectYouTubeAcquirer, select_candidate


def track(**changes):
    values = dict(title="Starboy", artist="The Weeknd, Daft Punk", album="Starboy", duration=230,
                  spotify_track_id="spotify-id", spotify_url="https://open.spotify.com/track/spotify-id",
                  source_provider="spotify")
    values.update(changes)
    return Track(**values)


def result(title="Starboy", artist="The Weeknd & Daft Punk", duration=230, item_id="video123"):
    return SourceResult("youtube_music", item_id, "song", title, artist,
                        duration=duration, source_url=f"https://music.youtube.com/watch?v={item_id}")


def test_strong_direct_candidate_is_selected():
    selected = select_candidate(track(), [result()])
    assert selected is not None
    assert selected.result.item_id == "video123"
    assert selected.score >= 0.82


@pytest.mark.parametrize("candidate", [
    result(artist="Unrelated Artist"), result(title="A Completely Different Song"),
    result(duration=400), result(title="Starboy (Live)"),
    result(title="Starboy Remix"), result(title="Starboy Acoustic"),
])
def test_unsafe_direct_candidates_are_rejected(candidate):
    assert select_candidate(track(), [candidate]) is None


def test_artist_title_presentation_and_multi_artist_credit_are_accepted():
    assert select_candidate(track(), [result(title="The Weeknd & Daft Punk - Starboy", artist="Uploader")]) is not None


def test_album_context_title_variation_is_accepted():
    requested = track(title="Earned It", artist="The Weeknd", album="Fifty Shades Of Grey", duration=252)
    assert select_candidate(requested, [result(title="Earned It - Fifty Shades Of Grey", artist="The Weeknd", duration=252)]) is not None


def test_acquirer_inspects_then_downloads_only_selected_candidate(tmp_path):
    class Source:
        def __init__(self): self.downloaded = []
        def inspect_search(self, query, limit):
            assert "Starboy" in query and limit == 5
            return [result(), result(artist="Wrong Artist", item_id="bad123")]
        def download_candidate(self, requested, video_id, output_dir, job_id):
            self.downloaded.append((video_id, job_id))
            output = Path(output_dir) / "track.mp3"
            output.write_bytes(b"audio")
            return output

    source = Source()
    acquired = DirectYouTubeAcquirer(source).download(track(), tmp_path, 17)
    assert acquired == tmp_path / "track.mp3"
    assert source.downloaded == [("video123", 17)]


def test_no_safe_candidate_is_typed_failure(tmp_path):
    class Source:
        def inspect_search(self, *_args, **_kwargs): return [result(artist="Wrong")]
    with pytest.raises(DownloadFailed) as error:
        DirectYouTubeAcquirer(Source()).download(track(), tmp_path)
    assert error.value.reason_code == "exact_match_unavailable"


def test_spotify_track_uses_direct_acquisition_without_spotdl(tmp_path, monkeypatch):
    output = tmp_path / "direct.mp3"
    monkeypatch.setattr(download.settings, "staging_path", str(tmp_path))
    monkeypatch.setattr(download.direct_client, "download", lambda *_: output)
    monkeypatch.setattr(download.client, "download", lambda *_: pytest.fail("SpotDL called"))
    assert download.download_track(track(), 9) == output


@pytest.mark.parametrize("origin", ["track", "album", "playlist"])
def test_all_resolved_spotify_track_origins_use_same_direct_path(origin, tmp_path, monkeypatch):
    requested = track(source_item_id=f"{origin}-item")
    output = tmp_path / f"{origin}.mp3"
    calls = []
    monkeypatch.setattr(download.settings, "staging_path", str(tmp_path))
    monkeypatch.setattr(download.direct_client, "download", lambda value, *_: calls.append(value) or output)
    assert download.download_track(requested) == output
    assert calls == [requested]


@pytest.mark.parametrize("failure", [
    DownloadFailed("exact_match_unavailable", "none", "validation", retryable=False),
    DownloadFailed("provider_unavailable", "failed", "download", retryable=True),
])
def test_direct_failure_falls_back_to_spotdl(failure, tmp_path, monkeypatch):
    fallback = tmp_path / "fallback.mp3"
    monkeypatch.setattr(download.settings, "staging_path", str(tmp_path))
    monkeypatch.setattr(download.direct_client, "download", lambda *_: (_ for _ in ()).throw(failure))
    monkeypatch.setattr(download.client, "download", lambda *_: fallback)
    assert download.download_track(track()) == fallback
