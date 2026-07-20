from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional

from app.database.session import get_db
from app.database.models import ScanHistory
from app.services import subsonic
from app.services.settings_service import get_settings_by_category, update_settings

router = APIRouter(prefix="/api/navidrome", tags=["navidrome"])

class TestConnectionRequest(BaseModel):
    url: str
    username: str
    password: str

class SaveConnectionRequest(BaseModel):
    url: str
    username: str
    password: str

@router.post("/test")
def test_connection(req: TestConnectionRequest):
    success, message, params = subsonic.ping(req.url, req.username, req.password)
    if not success:
        raise HTTPException(status_code=400, detail=message)

    info = subsonic.get_server_info(req.url, req.username, req.password)
    version = info.get("version")

    scan_status = subsonic.get_scan_status(req.url, req.username, req.password)
    song_count = scan_status.get("count", 0) if scan_status else 0

    return {
        "status": "success",
        "message": message,
        "version": version,
        "song_count": song_count
    }

@router.post("/save")
def save_connection(req: SaveConnectionRequest, db: Session = Depends(get_db)):
    success, message, params = subsonic.ping(req.url, req.username, req.password)
    if not success:
        raise HTTPException(status_code=400, detail=message)

    updates = {
        "navidrome_enabled": True,
        "navidrome_url": req.url,
        "navidrome_username": req.username,
        "navidrome_token": params["t"],
        "navidrome_salt": params["s"],
        "navidrome_connected": True
    }

    update_settings(db, "navidrome", updates)
    return {"status": "success"}

@router.get("/status")
def get_status(db: Session = Depends(get_db)):
    settings = get_settings_by_category(db, "navidrome")

    if not settings.get("navidrome_connected"):
        return {"connected": False}

    url = settings.get("navidrome_url")
    username = settings.get("navidrome_username")
    token = settings.get("navidrome_token")
    salt = settings.get("navidrome_salt")

    success, message, _ = subsonic.ping(url, username, token=token, salt=salt)

    if not success:
        return {"connected": False, "error": message}

    info = subsonic.get_server_info(url, username, token=token, salt=salt)
    version = info.get("version")

    scan_status = subsonic.get_scan_status(url, username, token=token, salt=salt)
    song_count = scan_status.get("count", 0) if scan_status else 0
    is_scanning = scan_status.get("scanning", False) if scan_status else False

    return {
        "connected": True,
        "version": version,
        "song_count": song_count,
        "is_scanning": is_scanning
    }

@router.post("/autodiscover")
def autodiscover():
    common_urls = [
        "http://navidrome:4533",
        "http://localhost:4533",
        "http://127.0.0.1:4533"
    ]

    reachable = []

    # We just do a basic HTTP GET to check if it looks like a subsonic server
    import urllib.request
    import urllib.error

    for url in common_urls:
        try:
            req = urllib.request.Request(f"{url}/rest/ping.view")
            with urllib.request.urlopen(req, timeout=2) as response:
                if response.status == 200:
                    reachable.append(url)
        except urllib.error.URLError:
            pass
        except Exception:
            pass

    return {"urls": reachable}

@router.post("/scan")
def trigger_scan(db: Session = Depends(get_db)):
    settings = get_settings_by_category(db, "navidrome")

    if not settings.get("navidrome_connected"):
        raise HTTPException(status_code=400, detail="Navidrome not connected")

    url = settings.get("navidrome_url")
    username = settings.get("navidrome_username")
    token = settings.get("navidrome_token")
    salt = settings.get("navidrome_salt")

    success = subsonic.trigger_scan(url, username, token=token, salt=salt)

    if success:
        from app.database.models import ScanHistory
        history = ScanHistory(
            trigger_type="manual",
            status="success",
            details="Manual scan triggered successfully"
        )
        db.add(history)
        db.commit()
        return {"status": "success"}
    else:
        from app.database.models import ScanHistory
        history = ScanHistory(
            trigger_type="manual",
            status="failed",
            error_message="Failed to trigger scan"
        )
        db.add(history)
        db.commit()
        raise HTTPException(status_code=500, detail="Failed to trigger scan")

@router.get("/scans/history")
def get_scan_history(db: Session = Depends(get_db)):
    from app.services.scan_manager import scan_manager
    scans = db.query(ScanHistory).order_by(ScanHistory.created_at.desc()).limit(10).all()
    return {
        "pending": scan_manager.scan_pending,
        "running": scan_manager.task_running,
        "history": [{"id": s.id, "trigger_type": s.trigger_type, "status": s.status, "tracks_found": s.tracks_found, "details": s.details, "error_message": s.error_message, "created_at": s.created_at.isoformat()} for s in scans]
    }
