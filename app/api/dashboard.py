import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import DownloadJob, Task
from app.database.session import get_db, SessionLocal
from app.services.dashboard import get_dashboard_snapshot, serialize_dashboard_activity
from app.domain.task import TaskStatus
from app.domain.download import JobStatus
from app.core.config import get_settings

settings = get_settings()

router = APIRouter(
    prefix="/api/dashboard",
    tags=["dashboard"],
)


@router.get("")
def dashboard_stats(db: Session = Depends(get_db)):
    return get_dashboard_snapshot(db)


@router.get("/activity")
def dashboard_activity(db: Session = Depends(get_db)):
    jobs = (
        db.execute(select(DownloadJob).order_by(DownloadJob.id.desc()).limit(10))
        .scalars()
        .all()
    )
    return [serialize_dashboard_activity(job) for job in jobs]


# Inside app/api/dashboard.py, update the stream_dashboard_data function:


@router.get("/stream")
async def stream_dashboard_data(request: Request):
    """Server-Sent Events endpoint for real-time dashboard updates."""

    async def event_generator():
        while True:
            if await request.is_disconnected():
                break

            db = SessionLocal()
            try:
                snapshot = get_dashboard_snapshot(db)

                jobs = (
                    db.execute(
                        select(DownloadJob).order_by(DownloadJob.id.desc()).limit(10)
                    )
                    .scalars()
                    .all()
                )
                activity = [serialize_dashboard_activity(job) for job in jobs]

                tasks = (
                    db.execute(
                        select(Task)
                        .where(
                            Task.status.in_(
                                (
                                    TaskStatus.QUEUED.value,
                                    TaskStatus.RUNNING.value,
                                    TaskStatus.PAUSED.value,
                                )
                            )
                        )
                        .order_by(Task.created_at.desc())
                    )
                    .scalars()
                    .all()
                )
                active_tasks = [
                    {
                        "id": t.id,
                        "name": t.name,
                        "status": t.status,
                        "total": t.total_items,
                        "completed": t.completed_items,
                        "failed": t.failed_items,
                        "skipped": t.skipped_items,
                        "current": t.current_item,
                        "type": t.task_type,
                    }
                    for t in tasks
                ]

                running_jobs = (
                    db.execute(
                        select(DownloadJob)
                        .where(DownloadJob.status == JobStatus.RUNNING.value)
                        .order_by(DownloadJob.started_at)
                    )
                    .scalars()
                    .all()
                )
                # NEW: Add cover_url
                workers = [
                    {"title": j.title, "artist": j.artist, "cover_url": j.cover_url}
                    for j in running_jobs
                ]

                payload = {
                    **snapshot,
                    "activity": activity,
                    "tasks": active_tasks,
                    "workers": workers,
                    "max_workers": settings.max_parallel_downloads,
                }

                yield f"data: {json.dumps(payload)}\n\n"
            finally:
                db.close()

            await asyncio.sleep(2)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
