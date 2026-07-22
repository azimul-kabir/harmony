from sqlalchemy.orm import Session
from app.database.models import AppSetting
from app.core.config import get_settings

DEFAULT_SETTINGS = [
    {"key": "timezone", "value": "Asia/Dhaka", "type": "string", "category": "general"},
    {"key": "date_format", "value": "DD/MM/YYYY", "type": "string", "category": "general"},
    {"key": "time_format", "value": "12h", "type": "string", "category": "general"},
    {"key": "audio_quality", "value": "128k", "type": "string", "category": "downloads"},
    {"key": "download_workers", "value": "4", "type": "int", "category": "downloads"},
    {"key": "retry_failed", "value": "true", "type": "boolean", "category": "downloads"},
    {"key": "playlist_sync_enabled", "value": "true", "type": "boolean", "category": "playlists"},
    {"key": "m3u_export_folder", "value": "/music/Playlists", "type": "string", "category": "playlists"},
    {"key": "theme", "value": "auto", "type": "string", "category": "appearance"},
    {"key": "spotify_genre_enrichment_enabled", "value": "false", "type": "boolean", "category": "spotify"},
]

def initialize_defaults(db: Session):
    for setting in DEFAULT_SETTINGS:
        exists = db.query(AppSetting).filter(AppSetting.key == setting["key"]).first()
        if not exists:
            value = setting["value"]
            if setting["key"] == "spotify_genre_enrichment_enabled":
                value = str(get_settings().spotify_genre_enrichment_enabled).lower()
            db.add(AppSetting(**(setting | {"value": value})))
    db.commit()

def get_settings_by_category(db: Session, category: str):
    settings = db.query(AppSetting).filter(AppSetting.category == category).all()
    return {s.key: _cast_value(s.value, s.type) for s in settings}

def update_settings(db: Session, category: str, updates: dict):
    for key, value in updates.items():
        setting = db.query(AppSetting).filter(AppSetting.key == key, AppSetting.category == category).first()
        if setting:
            setting.value = str(value).lower() if isinstance(value, bool) else str(value)
    db.commit()

def _cast_value(value: str, val_type: str):
    if val_type == "int": return int(value)
    if val_type == "boolean": return value.lower() in ("true", "1", "yes")
    return value
