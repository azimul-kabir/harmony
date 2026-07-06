from fastapi import APIRouter
from sqlalchemy.orm import Session

from app.database.crud import library_statistics
from app.database.session import SessionLocal

router = APIRouter(prefix="/api/library", tags=["Library"])


@router.get("/statistics")
def statistics():
    db: Session = SessionLocal()

    try:
        return library_statistics(db)
    finally:
        db.close()