from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
from app.database.session import get_db
from app.services import settings_service

from app.core.config import get_settings

from app.web.templates import (
    templates,
    template_context,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/settings")
def settings_page(request: Request):
    settings = get_settings()

    return templates.TemplateResponse(
        "settings.html",
        template_context(
            request=request,
            settings=settings,
            spotify_credentials_configured=bool(settings.spotify_client_id and settings.spotify_client_secret),
            page="settings",
        ),
    )

@router.get("/{category}")
def get_category_settings(category: str, db: Session = Depends(get_db)):
    return settings_service.get_settings_by_category(db, category)

@router.put("/{category}")
def update_category_settings(category: str, updates: dict, db: Session = Depends(get_db)):
    settings_service.update_settings(db, category, updates)
    return {"status": "success"}
