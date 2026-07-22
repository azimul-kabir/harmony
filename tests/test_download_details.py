from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database.base import Base
from app.database.models import DownloadJob
from app.services.download_dashboard import DETAIL_EVENT_LIMIT, download_details


def make_job(**kwargs):
    return DownloadJob(spotify_url="https://secret.example/token", title="Song", artist="Artist", **kwargs)


def test_details_are_safe_and_timestamp_derived():
    created = datetime(2026, 7, 23, 10, 0, 0)
    job = make_job(status="failed", album="Album", created_at=created,
                   started_at=created + timedelta(seconds=5),
                   completed_at=created + timedelta(seconds=150),
                   output_file="/downloads/private.mp3", source_url="https://provider/private",
                   error="traceback /tmp/secret", error_message="raw provider message")
    details = download_details(job)
    assert details["queue_wait_seconds"] == 5
    assert details["run_duration_seconds"] == 145
    assert [event["key"] for event in details["events"]] == ["queued", "started", "failed"]
    serialized = str(details)
    assert "/downloads" not in serialized and "provider/private" not in serialized
    assert "traceback" not in serialized and "raw provider" not in serialized
    assert details["can_cancel"] is False and details["can_retry"] is False


def test_details_nulls_bad_durations_and_event_bound():
    job = make_job(status="running", created_at=datetime(2026, 7, 23, 11),
                   started_at=datetime(2026, 7, 23, 10))
    details = download_details(job)
    assert details["finished_at"] is None
    assert details["run_duration_seconds"] is None
    assert details["queue_wait_seconds"] == 0
    assert details["can_cancel"] is True
    assert len(details["events"]) <= DETAIL_EVENT_LIMIT


def test_details_endpoint_returns_safe_record_and_404():
    from fastapi import HTTPException
    from app.api.downloads import get_download_details
    from app.database.session import SessionLocal

    db = SessionLocal()
    try:
        job = make_job(status="queued", created_at=datetime(2026, 7, 23, 10))
        db.add(job); db.commit(); db.refresh(job)
        response = get_download_details(job.id, db)
        try:
            get_download_details(999999, db)
        except HTTPException as exc:
            missing = exc
    finally:
        db.close()
    assert response["id"] == job.id
    assert missing.status_code == 404
