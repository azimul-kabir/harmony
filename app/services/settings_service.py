from sqlalchemy.orm import Session
from app.database.models import AppSetting
from app.core.config import get_settings

RUNTIME_SETTING_DEFINITIONS = {
    "spotify_playlist_metadata_timeout_seconds": ("downloads", "int", 300, 14400),
    "youtube_music_timeout_seconds": ("downloads", "int", 30, 3600),
    "youtube_music_max_playlist_items": ("downloads", "int", 1, 5000),
    "youtube_music_max_search_results": ("downloads", "int", 1, 100),
    "youtube_music_max_queue_items": ("downloads", "int", 1, 5000),
    "cover_art_archive_timeout_seconds": ("metadata", "float", 1, 120),
    "navidrome_timeout_seconds": ("navidrome", "float", 1, 120),
    "navidrome_playlist_reimport_enabled": ("navidrome", "boolean", None, None),
    "navidrome_playlist_reimport_debounce_seconds": ("navidrome", "float", 0, 300),
    "navidrome_playlist_reimport_poll_seconds": ("navidrome", "float", 0.25, 60),
    "navidrome_playlist_reimport_scan_timeout_seconds": ("navidrome", "float", 10, 3600),
    "library_watcher_enabled": ("library", "boolean", None, None),
    "library_watcher_debounce_seconds": ("library", "float", 0.1, 60),
}

# v2 rows may remain in upgraded databases. Keep them readable at the schema
# level, but do not expose or mutate settings that no longer control behavior.
RETIRED_SETTING_KEYS = {
    "default_download_source",
    "playlist_sync_enabled",
    "m3u_export_folder",
    "spotify_genre_enrichment_enabled",
    "spotify_genre_max_values",
    "spotify_genre_include_featured_fallback",
    "spotify_genre_merge_featured",
    "spotify_genre_replace_existing",
}

DEFAULT_SETTINGS = [
    {"key": "timezone", "value": "Asia/Dhaka", "type": "string", "category": "general"},
    {"key": "date_format", "value": "DD/MM/YYYY", "type": "string", "category": "general"},
    {"key": "time_format", "value": "12h", "type": "string", "category": "general"},
    {"key": "audio_quality", "value": "128k", "type": "string", "category": "downloads"},
    {"key": "download_workers", "value": "2", "type": "int", "category": "downloads"},
    {"key": "retry_failed", "value": "true", "type": "boolean", "category": "downloads"},
    {"key": "youtube_music_enabled", "value": "true", "type": "boolean", "category": "downloads"},
    {"key": "theme", "value": "auto", "type": "string", "category": "appearance"},
]


def _runtime_defaults():
    runtime = get_settings()
    return [
        {
            "key": key,
            "value": str(getattr(runtime, key)).lower()
            if isinstance(getattr(runtime, key), bool)
            else str(getattr(runtime, key)),
            "type": definition[1],
            "category": definition[0],
        }
        for key, definition in RUNTIME_SETTING_DEFINITIONS.items()
    ]


def initialize_defaults(db: Session):
    for setting in DEFAULT_SETTINGS + _runtime_defaults():
        exists = db.query(AppSetting).filter(AppSetting.key == setting["key"]).first()
        if not exists:
            db.add(AppSetting(**setting))
    db.commit()
    apply_runtime_overrides(db)

def get_settings_by_category(db: Session, category: str):
    settings = db.query(AppSetting).filter(
        AppSetting.category == category,
        AppSetting.key.not_in(RETIRED_SETTING_KEYS),
    ).all()
    return {s.key: _cast_value(s.value, s.type) for s in settings}

def update_settings(db: Session, category: str, updates: dict):
    for key, value in updates.items():
        if key in RETIRED_SETTING_KEYS:
            continue
        setting = db.query(AppSetting).filter(AppSetting.key == key, AppSetting.category == category).first()
        if setting:
            if key == "download_workers":
                try:
                    cast_value = int(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError("download_workers must be a number from 1 to 8.") from exc
                if not 1 <= cast_value <= 8:
                    raise ValueError("download_workers must be between 1 and 8.")
            else:
                cast_value = _validate_runtime_value(key, value) if key in RUNTIME_SETTING_DEFINITIONS else value
            setting.value = str(cast_value).lower() if isinstance(cast_value, bool) else str(cast_value)
    db.commit()
    apply_runtime_overrides(db)


def configured_download_workers(db: Session) -> int:
    """Apply the persisted startup worker count to the authoritative runtime."""
    downloads = get_settings_by_category(db, "downloads")
    try:
        count = int(downloads.get("download_workers", 2))
    except (TypeError, ValueError):
        count = 2
    count = max(1, min(8, count))
    get_settings().max_parallel_downloads = count
    return count


def apply_runtime_overrides(db: Session):
    runtime = get_settings()
    rows = db.query(AppSetting).filter(
        AppSetting.key.in_(RUNTIME_SETTING_DEFINITIONS)
    ).all()
    for row in rows:
        setattr(runtime, row.key, _cast_value(row.value, row.type))


def _validate_runtime_value(key: str, value):
    _, value_type, minimum, maximum = RUNTIME_SETTING_DEFINITIONS[key]
    try:
        if value_type == "boolean":
            if isinstance(value, bool):
                cast_value = value
            elif str(value).lower() in ("true", "1", "yes"):
                cast_value = True
            elif str(value).lower() in ("false", "0", "no"):
                cast_value = False
            else:
                raise ValueError
        elif value_type == "int":
            cast_value = int(value)
        elif value_type == "float":
            cast_value = float(value)
        else:
            cast_value = str(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid value for {key}.") from exc
    if minimum is not None and cast_value < minimum:
        raise ValueError(f"{key} must be at least {minimum}.")
    if maximum is not None and cast_value > maximum:
        raise ValueError(f"{key} must be at most {maximum}.")
    return cast_value

def _cast_value(value: str, val_type: str):
    if val_type == "int": return int(value)
    if val_type == "float": return float(value)
    if val_type == "boolean": return value.lower() in ("true", "1", "yes")
    return value
