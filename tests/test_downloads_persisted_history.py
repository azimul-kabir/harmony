from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database.base import Base
from app.database.models import DownloadJob, Task
from app.services.download_dashboard import download_diagnostics, download_history, get_download_snapshot


def test_production_shaped_jobs_remain_visible_without_parent_task():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        parent = Task(name="Album", spotify_url="spotify:album:parent", task_type="album_download", status="failed")
        unrelated = Task(name="Maintenance", spotify_url="internal", task_type="library_bulk", status="completed")
        db.add_all([parent, unrelated])
        db.flush()
        statuses = ["completed"] * 216 + ["failed"] * 19 + ["queued"] * 12 + ["skipped"] * 3
        now = datetime(2026, 7, 22, 12)
        for index, status in enumerate(statuses):
            db.add(DownloadJob(spotify_url=f"spotify:track:{index}", title=f"Track {index}", artist="Needle Artist" if index == 0 else "Artist", album="Needle Album" if index == 1 else "Album", status=status, task_id=parent.id if index < 9 else None, created_at=now + timedelta(seconds=index), completed_at=now if status in {"completed", "failed", "skipped"} else None))
        db.commit()

        snapshot = get_download_snapshot(db)
        assert snapshot["counts"] == {"running": 0, "queued": 12, "paused": 0, "completed": 216, "failed": 19, "cancelled": 0, "skipped": 3}
        assert snapshot["history"]["total"] == 250
        assert len(snapshot["jobs"]) == 250
        assert len(snapshot["queued"]) == 12
        assert any(item["status"] == "completed" and item["task_id"] == parent.id for item in snapshot["jobs"])
        assert all("output_file" not in item and "error" not in item for item in snapshot["jobs"])
        assert download_history(db, search="needle artist")["total"] == 1
        assert download_history(db, search="needle album")["total"] == 1
        assert download_history(db, status="skipped")["total"] == 3
        assert download_history(db, status="completed", page_size=25)["total"] == 216
        assert download_diagnostics(db)["download_jobs_total"] == 250


def test_download_routes_return_persisted_jobs_and_stream_route_is_not_shadowed():
    from app.api.downloads import download_counters, live_download_queue, persisted_download_history, router
    from app.database.session import SessionLocal

    db = SessionLocal()
    try:
        db.add(DownloadJob(spotify_url="spotify:track:route", title="Route title", artist="Route artist", album="Route album", status="queued"))
        db.commit()
        assert download_counters(db)["counts"]["queued"] == 1
        assert live_download_queue(db)["queued"][0]["title"] == "Route title"
        history = persisted_download_history(page=1, page_size=100, search="route album", db=db)
        assert history["total"] == 1 and history["items"][0]["id"]
    finally:
        db.close()
    # /stream is declared before /{job_id}, so it cannot become an integer-path 422.
    stream_route = next(route for route in router.routes if getattr(route, "path", None) == "/api/downloads/stream")
    detail_route = next(route for route in router.routes if getattr(route, "path", None) == "/api/downloads/{job_id}")
    assert router.routes.index(stream_route) < router.routes.index(detail_route)
