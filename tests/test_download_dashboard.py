from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database.base import Base
from app.database.models import DownloadJob
from app.domain.download import JobStatus
from app.services.download_dashboard import TERMINAL_STATUSES, get_download_snapshot


def test_download_snapshot_has_global_counts_and_safe_bounded_job_details():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            DownloadJob(spotify_url="spotify:running", title="Running", artist="Artist", status=JobStatus.RUNNING.value),
            DownloadJob(spotify_url="spotify:queued", title="Queued", artist="Artist", status=JobStatus.QUEUED.value),
            DownloadJob(spotify_url="spotify:done", title="Done", artist="Artist", status=JobStatus.COMPLETED.value),
            DownloadJob(spotify_url="spotify:failed", title="Failed", artist="Artist", status=JobStatus.FAILED.value, error="Provider unavailable"),
            DownloadJob(spotify_url="spotify:cancelled", title="Cancelled", artist="Artist", status=JobStatus.CANCELLED.value),
        ])
        db.commit()

        snapshot = get_download_snapshot(db, limit=2)

        assert snapshot["summary"] == {"running": 1, "queued": 1, "completed": 1, "attention": 2}
        assert [item["title"] for item in snapshot["jobs"]] == ["Cancelled", "Failed"]
        assert snapshot["jobs"][1]["error"] == "Provider unavailable"
        assert "output_file" not in snapshot["jobs"][0]


def test_cancelled_downloads_are_terminal_history():
    assert JobStatus.CANCELLED.value in TERMINAL_STATUSES
