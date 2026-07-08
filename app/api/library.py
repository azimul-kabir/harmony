from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.crud import library_statistics
from app.database.session import get_db
from app.services.scanner import scan_library

router = APIRouter(prefix="/api/library", tags=["Library"])


@router.get("/statistics")
def statistics(db: Session = Depends(get_db)):
    return library_statistics(db)


@router.post("/scan")
def scan(db: Session = Depends(get_db)):
    result = scan_library("/music", db)

    return {
        "status": "completed",
        **result,
    }