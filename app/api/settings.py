import json
import shutil
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session
from app.database.session import get_db
from app.services import settings_service
from app.services.operations import create_backup, export_settings, import_settings, restore_backup

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


@router.get("/operations/settings-export")
def download_settings(db: Session = Depends(get_db)):
    return JSONResponse(
        export_settings(db),
        headers={"Content-Disposition": "attachment; filename=harmony-settings.json"},
    )


@router.post("/operations/settings-import")
async def upload_settings(file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        payload = json.loads(await file.read())
        changed = import_settings(db, payload)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "success", "settings_imported": changed, "restart_recommended": True}


@router.get("/operations/backup")
def download_backup():
    try:
        path, filename = create_backup()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FileResponse(
        path,
        filename=filename,
        media_type="application/zip",
        background=BackgroundTask(lambda: shutil.rmtree(path.parent, ignore_errors=True)),
    )


@router.post("/operations/restore")
async def upload_backup(file: UploadFile = File(...)):
    try:
        payload = await file.read()
        if len(payload) > 2 * 1024 * 1024 * 1024:
            raise ValueError("Backup files larger than 2 GB are not accepted.")
        return restore_backup(payload)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
