import json
import shutil
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from app.database.session import get_db
from app.services import settings_service
from app.services.operations import (
    MAX_RESTORE_BYTES,
    OperationBusyError,
    create_backup,
    export_settings,
    import_settings,
    restore_backup,
)

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
    except OperationBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
    # Starlette has already spooled the upload to a temporary file. Restore from
    # that file in a worker thread: reading it into memory can exhaust a small
    # NAS, and blocking the event loop freezes every page and live stream.
    if file.size is not None and file.size > MAX_RESTORE_BYTES:
        raise HTTPException(status_code=413, detail="Backup files larger than 2 GB are not accepted.")
    try:
        return await run_in_threadpool(restore_backup, file.file)
    except OperationBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
