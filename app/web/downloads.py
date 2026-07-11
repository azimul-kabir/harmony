from fastapi import APIRouter, Request
from app.core.config import get_settings
from app.web.templates import templates
from sqlalchemy import select

from app.database.models import DownloadJob
from app.database.session import SessionLocal

router = APIRouter()


@router.get("/downloads")
def downloads(request: Request):
    db = SessionLocal()

    try:
        jobs = (
            db.execute(
                select(DownloadJob).order_by(
                    DownloadJob.id.desc()
                )
            )
            .scalars()
            .all()
        )

        from app.core.config import get_settings

        settings = get_settings()
        return templates.TemplateResponse(
            "downloads.html",
            {
                "request": request,
                "jobs": jobs,
                "app_name": settings.app_name,
                "version": settings.app_version,
            },
        )

    finally:
        db.close()