from fastapi import APIRouter

from app.database.session import SessionLocal
from app.services.dashboard import get_dashboard_stats

from sqlalchemy import select

from app.database.models import DownloadJob

router = APIRouter(
    prefix="/api/dashboard",
    tags=["dashboard"],
)


@router.get("")
def dashboard_stats():
    db = SessionLocal()

    try:
        return get_dashboard_stats(db)

    finally:
        db.close()


@router.get("/activity")
def dashboard_activity():
    db = SessionLocal()

    try:
        jobs = (
            db.execute(
                select(DownloadJob)
                .order_by(DownloadJob.id.desc())
                .limit(10)
            )
            .scalars()
            .all()
        )

        return [
            {
                "status": job.status,
                "title": job.title,
                "artist": job.artist,
            }
            for job in jobs
        ]

    finally:
        db.close()