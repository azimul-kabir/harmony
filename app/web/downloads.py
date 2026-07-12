from fastapi import APIRouter, Request
from sqlalchemy import select

from app.database.models import DownloadJob
from app.database.session import SessionLocal

from app.web.templates import (
    templates,
    template_context,
)

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

        return templates.TemplateResponse(
            "downloads.html",
            template_context(
                request=request,
                jobs=jobs,
            ),
        )

    finally:
        db.close()