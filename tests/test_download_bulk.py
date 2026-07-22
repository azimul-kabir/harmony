from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database.base import Base
from app.database.models import DownloadJob
from app.services.download_bulk import MAX_BULK_IDS, run_bulk_action


def make_job(status):
    return DownloadJob(spotify_url=f"secret:{status}", title=status, artist="Artist", status=status)


def test_retry_cancel_and_history_bulk_rules():
    engine = create_engine("sqlite:///:memory:"); Base.metadata.create_all(engine)
    with Session(engine) as db:
        failed, queued, completed = make_job("failed"), make_job("queued"), make_job("completed")
        db.add_all((failed, queued, completed)); db.commit()
        result = run_bulk_action(db, "retry", [failed.id, queued.id, completed.id])
        assert result == {"action": "retry", "requested": 3, "eligible": 1, "succeeded": 1, "skipped": 2, "failed": 0, "result_code": "partial"}
        assert db.get(DownloadJob, failed.id).status == "queued"
        cancelled = run_bulk_action(db, "cancel", [failed.id, completed.id])
        assert cancelled["succeeded"] == 1 and cancelled["skipped"] == 1
        cleared = run_bulk_action(db, "clear_history", [completed.id, failed.id])
        assert cleared["succeeded"] == 2 and db.get(DownloadJob, failed.id) is None


def test_global_history_actions_are_terminal_only_and_idempotent():
    engine = create_engine("sqlite:///:memory:"); Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all((make_job("completed"), make_job("failed"), make_job("cancelled"), make_job("running"))); db.commit()
        result = run_bulk_action(db, "clear_completed_history", [])
        assert result["succeeded"] == 1
        result = run_bulk_action(db, "clear_failed_cancelled_history", [])
        assert result["succeeded"] == 2
        assert run_bulk_action(db, "clear_failed_cancelled_history", [])["succeeded"] == 0
        assert db.query(DownloadJob).filter_by(status="running").count() == 1


def test_bulk_actions_are_allowlisted_and_bounded():
    engine = create_engine("sqlite:///:memory:"); Base.metadata.create_all(engine)
    with Session(engine) as db:
        try:
            run_bulk_action(db, "delete_files", [])
        except ValueError as exc:
            assert "Unsupported" in str(exc)
        else:
            assert False
        try:
            run_bulk_action(db, "retry", list(range(MAX_BULK_IDS + 1)))
        except ValueError as exc:
            assert "at most" in str(exc)
        else:
            assert False
