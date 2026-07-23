"""Regression coverage for durable POST /api/downloads queue creation."""

import pytest
from fastapi import HTTPException

from app.api import downloads
from app.api.schemas.download import DownloadRequest
from app.database.models import DownloadJob, Song
from app.database.session import SessionLocal
from app.domain.track import Track
from app.services.download_dashboard import serialize_outcome


def track(url: str) -> Track:
    identifier = url.rsplit("/", 1)[-1]
    return Track(title=f"Track {identifier}", artist="Artist", album="Album",
                 spotify_track_id=identifier, spotify_url=url)


def call_queue(url: str):
    db = SessionLocal()
    try:
        return downloads.queue_download(DownloadRequest(url=url), db), db
    except Exception:
        db.close()
        raise


def test_track_post_creates_queued_job_with_empty_terminal_outcome(monkeypatch):
    url = "https://open.spotify.com/track/track-one"
    monkeypatch.setattr(downloads, "resolve_track", lambda _: track(url))
    response, db = call_queue(url)
    try:
        job = db.get(DownloadJob, response["job_id"])
        assert response["status"] == "created"
        assert job is not None and job.status == "queued"
        assert response["outcome"] == {
            "status": "queued", "reason_code": None, "reason_message": None,
            "failure_stage": None, "provider": None, "retryable": False,
            "finished_at": None, "technical_detail": None,
        }
        assert job.reason_code is job.reason_message is job.failure_stage is None
        assert job.provider is job.technical_detail is None
        assert job.retryable is False
    finally:
        db.close()


def test_album_post_creates_queued_jobs(monkeypatch):
    url = "https://open.spotify.com/album/album-one"
    tracks = [track(f"https://open.spotify.com/track/album-{number}") for number in (1, 2)]
    monkeypatch.setattr("app.services.download_queue.resolve_album", lambda _: tracks)
    response, db = call_queue(url)
    try:
        assert response["status"] == "queued"
        assert len(response["job_ids"]) == 2
        assert db.query(DownloadJob).count() == 2
    finally:
        db.close()


def test_playlist_post_returns_queue_summary(monkeypatch):
    url = "https://open.spotify.com/playlist/playlist-one"
    monkeypatch.setattr(downloads, "download_playlist", lambda **_: {"queued": 3})
    response, db = call_queue(url)
    try:
        assert response == {"status": "queued", "summary": {"queued": 3}}
    finally:
        db.close()


def test_serializer_failure_after_commit_keeps_success_and_single_job(monkeypatch):
    url = "https://open.spotify.com/track/serializer-one"
    monkeypatch.setattr(downloads, "resolve_track", lambda _: track(url))
    monkeypatch.setattr(downloads, "serialize_outcome", lambda _: (_ for _ in ()).throw(RuntimeError("bad serializer")))
    response, db = call_queue(url)
    try:
        assert response == {"status": "created", "job_id": response["job_id"]}
        assert db.query(DownloadJob).count() == 1
    finally:
        db.close()


def test_track_post_allows_redownload_of_a_deleted_library_track(monkeypatch):
    url = "https://open.spotify.com/track/deleted-track"
    monkeypatch.setattr(downloads, "resolve_track", lambda _: track(url))
    db = SessionLocal()
    try:
        db.add(Song(
            path="/music/Artist/Album/Track deleted-track.mp3",
            filename="Track deleted-track.mp3", title="Track deleted-track",
            artist="Artist", album="Album", spotify_track_id="deleted-track",
            availability_status="missing",
        ))
        db.commit()
    finally:
        db.close()

    response, db = call_queue(url)
    try:
        assert response["status"] == "created"
        assert db.get(DownloadJob, response["job_id"]) is not None
    finally:
        db.close()


def test_malformed_or_unsupported_url_is_a_structured_4xx():
    db = SessionLocal()
    try:
        with pytest.raises(HTTPException) as caught:
            downloads.queue_download(DownloadRequest(url="not-a-spotify-url"), db)
        assert caught.value.status_code == 422
        assert caught.value.detail["code"] == "invalid_spotify_url"
    finally:
        db.close()


def test_terminal_rows_keep_structured_reasons():
    failed = DownloadJob(spotify_url="spotify:track:failed", title="Failed", artist="Artist", status="failed",
                         reason_code="download_timeout", reason_message="The download timed out.",
                         failure_stage="download", provider="spotdl", retryable=True,
                         technical_detail="TimeoutError")
    skipped = DownloadJob(spotify_url="spotify:track:skipped", title="Skipped", artist="Artist", status="skipped",
                          reason_code="already_exists", reason_message="The destination file already exists.",
                          failure_stage="preflight", provider="spotdl")
    assert serialize_outcome(failed)["reason_code"] == "download_timeout"
    assert serialize_outcome(failed)["retryable"] is True
    assert serialize_outcome(skipped)["reason_code"] == "already_exists"
