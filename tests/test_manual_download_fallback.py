import json

import pytest

from app.database.models import DownloadJob
from app.database.session import SessionLocal
from app.services.download_dashboard import download_details
from app.services.manual_download_fallback import queue_manual_fallback
from app.workers import download_worker


VIDEO_URL = "https://music.youtube.com/watch?v=manual12345"


def _failed_job(**values):
    reason_code = values.pop("reason_code", "fallback_match_unavailable")
    return DownloadJob(
        spotify_url="https://open.spotify.com/track/original",
        source_provider="spotify",
        source_item_id="original",
        source_url="https://open.spotify.com/track/original",
        spotify_track_id="original",
        title="Original title",
        artist="Original artist",
        album="Original album",
        spotify_artist_ids=json.dumps([]),
        status="failed",
        reason_code=reason_code,
        **values,
    )


def test_manual_fallback_creates_new_job_and_preserves_failed_history():
    with SessionLocal() as db:
        original = _failed_job()
        db.add(original)
        db.commit()

        fallback = queue_manual_fallback(db, job_id=original.id, url=VIDEO_URL)

        db.refresh(original)
        assert original.status == "failed"
        assert fallback.id != original.id
        assert fallback.status == "queued"
        assert fallback.source_provider == "spotify"
        assert fallback.spotify_track_id == "original"
        assert fallback.manual_fallback_url == VIDEO_URL
        assert download_details(original)["can_manual_fallback"] is True


def test_manual_fallback_rejects_non_track_and_ineligible_failure():
    with SessionLocal() as db:
        ineligible = _failed_job(reason_code="disk_full")
        db.add(ineligible)
        db.commit()

        with pytest.raises(ValueError, match="failed matching jobs"):
            queue_manual_fallback(db, job_id=ineligible.id, url=VIDEO_URL)

        ineligible.reason_code = "provider_no_match"
        db.commit()
        with pytest.raises(ValueError, match="specific YouTube"):
            queue_manual_fallback(
                db,
                job_id=ineligible.id,
                url="https://music.youtube.com/playlist?list=PLnotatrack",
            )


def test_worker_uses_approved_url_but_keeps_original_source_identity(
    tmp_path, monkeypatch
):
    with SessionLocal() as db:
        job = _failed_job()
        job.status = "running"
        job.reason_code = None
        job.manual_fallback_url = VIDEO_URL
        job.attempt_count = 1
        db.add(job)
        db.commit()
        db.refresh(job)

        acquired = tmp_path / "manual.mp3"
        acquired.write_bytes(b"audio")
        library_file = tmp_path / "music" / "manual.mp3"
        seen = {}

        monkeypatch.setattr(download_worker, "write_genres", lambda *args, **kwargs: None)

        def download(track, _job_id):
            seen["provider"] = track.source_provider
            seen["item_id"] = track.source_item_id
            seen["url"] = track.source_url
            return acquired

        monkeypatch.setattr(download_worker, "download_track", download)
        monkeypatch.setattr(
            download_worker, "import_downloaded_track", lambda **kwargs: library_file
        )
        monkeypatch.setattr(
            download_worker, "export_m3us_for_source_track", lambda *args: 0
        )

        download_worker.process_job(db, job)
        db.refresh(job)

        assert job.status == "completed"
        assert job.source_provider == "spotify"
        assert seen == {
            "provider": "youtube_music",
            "item_id": "manual12345",
            "url": VIDEO_URL,
        }
