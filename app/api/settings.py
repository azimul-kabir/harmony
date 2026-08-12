from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database.session import get_db
from app.services import settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/{category}")
def get_category_settings(category: str, db: Session = Depends(get_db)):
    return settings_service.get_settings_by_category(db, category)


@router.put("/{category}")
def update_category_settings(
    category: str,
    updates: dict,
    db: Session = Depends(get_db),
):
    try:
        settings_service.update_settings(db, category, updates)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "success"}
