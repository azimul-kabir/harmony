from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import DownloadJob
from app.database.session import get_db
from app.services.dashboard import get_dashboard_stats

router = APIRouter(
    prefix="/api/dashboard",
    tags=["dashboard"],
)

@router.get("")
def dashboard_stats(db: Session = Depends(get_db)):
    return get_dashboard_stats(db)

@router.get("/activity")
def dashboard_activity(db: Session = Depends(get_db)):
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
