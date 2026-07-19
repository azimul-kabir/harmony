from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.session import get_db
from app.services import settings_service
from app.web.templates import templates, template_context

router = APIRouter(tags=["web"])

@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db)):
    # 1. Ensure our default database settings exist
    settings_service.initialize_defaults(db)
    
    # 2. Fetch the current settings to populate the form
    downloads = settings_service.get_settings_by_category(db, "downloads")
    playlists = settings_service.get_settings_by_category(db, "playlists")
    appearance = settings_service.get_settings_by_category(db, "appearance")
    
    return templates.TemplateResponse(
        "settings.html",
        template_context(
            request=request, 
            page="settings",
            downloads=downloads,
            playlists=playlists,
            appearance=appearance,
            settings=get_settings()
        ),
    )
