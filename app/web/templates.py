from fastapi.templating import Jinja2Templates
from zoneinfo import ZoneInfo
from datetime import datetime

from app.core.config import get_settings
from app.database.session import SessionLocal
from app.services import settings_service

templates = Jinja2Templates(directory="app/templates")

def format_tz(value, tz_str="UTC", fmt="%b %d, %H:%M"):
    """Jinja2 filter to convert UTC datetimes to the user's timezone."""
    if not value:
        return "Never"
    
    # If the database returned a string, parse it into a datetime object
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
            
    # Ensure the datetime is UTC-aware
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))
        
    # Safely fall back to UTC if the setting is blank or invalid
    try:
        target_tz = ZoneInfo(tz_str if tz_str else "UTC")
    except Exception:
        target_tz = ZoneInfo("UTC")
        
    return value.astimezone(target_tz).strftime(fmt)

# Register the custom filter so HTML files can use it
templates.env.filters["format_tz"] = format_tz

settings = get_settings()

def template_context(**kwargs):
    # Open a local database session just for template context injection
    db = SessionLocal()
    try:
        appearance = settings_service.get_settings_by_category(db, "appearance")
        general = settings_service.get_settings_by_category(db, "general")
    finally:
        db.close()

    return {
        "app_name": settings.app_name,
        "version": settings.app_version,
        "page": "",
        "appearance": appearance,
        "general": general,  # <-- Now EVERY page knows your timezone setting!
        **kwargs,
    }
