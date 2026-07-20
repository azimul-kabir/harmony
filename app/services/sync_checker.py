import asyncio
import time
import threading
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import Song
from app.services import subsonic
from app.services.settings_service import get_settings_by_category

_cache = None
_last_update = 0
_lock = threading.Lock()

def get_network_sync_status(settings):
    if not settings.get("navidrome_connected"):
        return {"connected": False, "online": False}

    url = settings.get("navidrome_url")
    username = settings.get("navidrome_username")
    token = settings.get("navidrome_token")
    salt = settings.get("navidrome_salt")

    start_time = time.time()
    success, _, _ = subsonic.ping(url, username, token=token, salt=salt)
    latency = int((time.time() - start_time) * 1000)

    if not success:
        return {"connected": True, "online": False, "latency": latency}

    scan_status = subsonic.get_scan_status(url, username, token=token, salt=salt)
    if not scan_status:
        return {"connected": True, "online": True, "latency": latency, "error": "Could not fetch scan status"}

    return {
        "connected": True,
        "online": True,
        "latency": latency,
        "navidrome_count": scan_status.get("count", 0),
        "is_scanning": scan_status.get("scanning", False)
    }

def check_sync_status(db: Session, force: bool = False):
    global _cache, _last_update

    with _lock:
        if not force and _cache is not None and (time.time() - _last_update < 30):
            harmony_count = db.scalar(select(func.count(Song.id))) or 0
            _cache["harmony_count"] = harmony_count
            if "navidrome_count" in _cache:
                _cache["delta"] = harmony_count - _cache["navidrome_count"]
            return _cache.copy()

    settings = get_settings_by_category(db, "navidrome")
    status = get_network_sync_status(settings)

    harmony_count = db.scalar(select(func.count(Song.id))) or 0
    status["harmony_count"] = harmony_count
    if "navidrome_count" in status:
        status["delta"] = harmony_count - status["navidrome_count"]

    with _lock:
        _cache = status.copy()
        _last_update = time.time()

    return status

async def check_sync_status_async(db: Session):
    global _cache, _last_update

    with _lock:
        if _cache is not None and (time.time() - _last_update < 30):
            harmony_count = db.scalar(select(func.count(Song.id))) or 0
            _cache["harmony_count"] = harmony_count
            if "navidrome_count" in _cache:
                _cache["delta"] = harmony_count - _cache["navidrome_count"]
            return _cache.copy()

    settings = get_settings_by_category(db, "navidrome")
    harmony_count = db.scalar(select(func.count(Song.id))) or 0

    status = await asyncio.to_thread(get_network_sync_status, settings)

    status["harmony_count"] = harmony_count
    if "navidrome_count" in status:
        status["delta"] = harmony_count - status["navidrome_count"]

    with _lock:
        _cache = status.copy()
        _last_update = time.time()

    return status
