from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.database.session import SessionLocal
from app.services import settings_service

templates = Jinja2Templates(
    directory="app/templates",
)

settings = get_settings()

def template_context(**kwargs):
    # Open a local database session just for template context injection
    db = SessionLocal()
    try:
        appearance = settings_service.get_settings_by_category(db, "appearance")
    finally:
        db.close()

    return {
        "app_name": settings.app_name,
        "version": settings.app_version,
        "page": "",
        "appearance": appearance,
        **kwargs,
    }
