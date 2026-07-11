from fastapi import APIRouter

from app.database.session import SessionLocal
from app.services.library_scanner import scan_library

router = APIRouter(
    prefix="/api/library",
    tags=["library"],
)


@router.post("/rescan")
def rescan():
    db = SessionLocal()

    try:
        scan_library(db)

        return {
            "status": "ok",
        }

    finally:
        db.close()