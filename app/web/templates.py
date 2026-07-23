from fastapi.templating import Jinja2Templates
from zoneinfo import ZoneInfo
from datetime import datetime
from pathlib import Path

from app.core.config import get_settings
from app.database.session import SessionLocal
from app.services import settings_service

templates = Jinja2Templates(directory="app/templates")

def format_tz(value, tz_str="UTC", fmt="%b %d, %H:%M"):
    if not value: return "Never"
    if isinstance(value, str):
        try: value = datetime.fromisoformat(value)
        except ValueError: return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))
    try: target_tz = ZoneInfo(tz_str if tz_str else "UTC")
    except Exception: target_tz = ZoneInfo("UTC")
        
    return value.astimezone(target_tz).strftime(fmt)

templates.env.filters["format_tz"] = format_tz
settings = get_settings()


def _static_version(path: str) -> str:
    """Return a deployment-specific cache key for a bundled static asset."""
    try:
        return str((Path("app/static") / path).stat().st_mtime_ns)
    except OSError:
        # Rendering a page must not fail if an asset is absent during a deploy.
        return settings.app_version

def template_context(**kwargs):
    db = SessionLocal()
    try:
        appearance = settings_service.get_settings_by_category(db, "appearance")
        general = settings_service.get_settings_by_category(db, "general")
        spotify = settings_service.get_settings_by_category(db, "spotify")
    finally:
        db.close()

    # Convert UI settings into Python date formats
    df = general.get("date_format", "DD/MM/YYYY") if general else "DD/MM/YYYY"
    tf = general.get("time_format", "12h") if general else "12h"
    
    date_str = "%d/%m/%Y"
    if df == "MM/DD/YYYY": date_str = "%m/%d/%Y"
    elif df == "YYYY-MM-DD": date_str = "%Y-%m-%d"
    elif df == "MMM DD, YYYY": date_str = "%b %d, %Y"
    
    time_str = "%I:%M %p" if tf == "12h" else "%H:%M"
    datetime_fmt = f"{date_str} {time_str}"

    return {
        "app_name": settings.app_name,
        "version": settings.app_version,
        "app_js_version": _static_version("js/app.js"),
        "page": "",
        "appearance": appearance,
        "general": general,
        "spotify": spotify,
        "datetime_fmt": datetime_fmt, # Passed to the templates!
        **kwargs,
    }
