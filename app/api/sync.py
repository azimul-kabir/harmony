from fastapi import APIRouter

from app.database.session import SessionLocal
from app.services.sync import sync_all_sources

router = APIRouter(
    prefix="/api/sync",
    tags=["sync"],
)


@router.post("")
def sync():
    db = SessionLocal()

    try:
        summary = sync_all_sources(db)

        return summary

    finally:
        db.close()