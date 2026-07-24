from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database.base import Base
from app.database.models import DownloadJob
from app.domain.download import JobStatus
from app.services.download_dashboard import HISTORY_LIMIT, QUEUE_LIMIT, TERMINAL_STATUSES, get_download_snapshot


def job(url, title, status, **kwargs):
    return DownloadJob(spotify_url=url, title=title, artist="Artist", status=status, **kwargs)


def test_snapshot_counts_order_bounds_and_safe_serialization():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        stamp = datetime(2026, 7, 23, 10)
        db.add_all([
            job("secret://running-2", "Running two", "running", started_at=stamp, output_file="/downloads/private.mp3", error="raw provider error", pipeline_stage="downloading", progress_percent=42, worker_name="download-worker-1", transfer_rate_bps=1024, eta_seconds=9),
            job("secret://running-1", "Running one", "running", started_at=stamp),
            job("secret://queue-2", "Queue two", "queued", created_at=stamp),
            job("secret://queue-1", "Queue one", "queued", created_at=stamp),
            job("secret://paused", "Paused", "paused"), job("secret://done", "Done", "completed"),
            job("secret://failed", "Failed", "failed"), job("secret://cancelled", "Cancelled", "cancelled"),
        ])
        db.commit()
        snapshot = get_download_snapshot(db, queue_limit=999, history_limit=999)
        assert snapshot["counts"] == {"running": 2, "queued": 2, "paused": 1, "completed": 1, "failed": 1, "cancelled": 1, "skipped": 0}
        assert [item["title"] for item in snapshot["active"]] == ["Running two", "Running one"]
        assert snapshot["active"][0]["stage"] == "downloading"
        assert snapshot["active"][0]["progress"] == 42
        assert snapshot["active"][0]["worker"] == "download-worker-1"
        assert snapshot["active"][0]["transfer_rate_bps"] == 1024
        assert snapshot["active"][0]["eta_seconds"] == 9
        assert [item["title"] for item in snapshot["queued"]] == ["Queue two", "Queue one"]
        assert [item["position"] for item in snapshot["queued"]] == [1, 2]
        assert all("output_file" not in item and "spotify_url" not in item and "error" not in item for group in (snapshot["active"], snapshot["queued"], snapshot["paused"], snapshot["jobs"]) for item in group)
        assert len(snapshot["jobs"]) <= HISTORY_LIMIT and QUEUE_LIMIT == 25


def test_empty_queue_and_cancelled_terminal_history():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        snapshot = get_download_snapshot(db)
        assert snapshot["active"] == snapshot["queued"] == snapshot["paused"] == []
    assert JobStatus.CANCELLED.value in TERMINAL_STATUSES
