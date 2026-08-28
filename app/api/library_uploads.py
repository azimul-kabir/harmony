"""Review-first browser upload endpoints for the managed music library."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.logging import logger
from app.database.session import SessionLocal
from app.services.library_uploads import (
    UploadValidationError,
    create_batch,
    discard_batch,
    import_batch,
    load_batch,
    save_upload,
)
from app.services.navidrome import NavidromeClient, NavidromeError


router = APIRouter(prefix="/api/library/uploads", tags=["library"])


class UploadMetadata(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    artist: str | None = Field(default=None, max_length=500)
    album_artist: str | None = Field(default=None, max_length=500)
    album: str | None = Field(default=None, max_length=500)
    genre: str | None = Field(default=None, max_length=200)
    year: int | None = Field(default=None, ge=0, le=9999)
    track: int | None = Field(default=None, ge=0, le=9999)
    disc: int | None = Field(default=None, ge=0, le=999)


class UploadSelection(BaseModel):
    id: str
    metadata: UploadMetadata | None = None


class ImportUploadBatch(BaseModel):
    items: list[UploadSelection] = Field(min_length=1, max_length=200)
    scan_navidrome: bool = True


def _bad_upload(error: Exception) -> HTTPException:
    logger.warning("Library upload rejected: {}", error)
    return HTTPException(status_code=400, detail=str(error))


@router.post("/batches", summary="Create an isolated Library upload batch")
def start_upload_batch():
    return create_batch()


@router.get("/batches/{batch_id}", summary="Read a staged upload review")
def get_upload_batch(batch_id: str):
    try:
        return load_batch(batch_id)
    except UploadValidationError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/batches/{batch_id}/files", summary="Stage and inspect audio files")
def upload_audio_files(batch_id: str, files: list[UploadFile] = File(...)):
    settings = get_settings()
    if not files:
        raise HTTPException(status_code=400, detail="Choose at least one audio file.")
    try:
        manifest = load_batch(batch_id)
        if len(manifest["items"]) + len(files) > settings.library_upload_max_files:
            raise UploadValidationError("This batch contains too many files.")
        items = []
        errors = []
        for upload in files:
            try:
                try:
                    items.append(save_upload(
                        batch_id,
                        upload.filename,
                        upload.file,
                        max_bytes=settings.library_upload_max_file_bytes,
                    ))
                except (UploadValidationError, OSError, ValueError) as error:
                    logger.warning("Library upload file rejected: {}", error)
                    errors.append({"filename": upload.filename, "error": str(error)})
                except Exception:
                    logger.exception("Library upload container inspection failed")
                    errors.append({"filename": upload.filename, "error": "The file is not a readable supported audio container."})
            finally:
                upload.file.close()
        return {"batch_id": batch_id, "items": items, "errors": errors}
    except UploadValidationError as error:
        raise _bad_upload(error) from error
    except (OSError, ValueError) as error:
        raise _bad_upload(error) from error


@router.post("/batches/{batch_id}/import", summary="Confirm, organize, and index staged audio")
async def confirm_upload_batch(batch_id: str, request: ImportUploadBatch):
    db = SessionLocal()
    try:
        try:
            result = import_batch(
                db,
                batch_id,
                [
                    {"id": item.id, "metadata": item.metadata.model_dump(exclude_unset=True) if item.metadata else {}}
                    for item in request.items
                ],
            )
        except UploadValidationError as error:
            raise _bad_upload(error) from error
    finally:
        db.close()

    result["navidrome"] = {"status": "not_requested"}
    if request.scan_navidrome and result["imported"]:
        try:
            scan = await NavidromeClient().start_scan(full_scan=False)
            result["navidrome"] = {"status": "requested", **scan}
        except NavidromeError as error:
            logger.warning("Library upload imported, but Navidrome scan failed: {}", error)
            result["navidrome"] = {"status": "failed", "message": str(error)}
    return result


@router.delete("/batches/{batch_id}", status_code=204, summary="Discard staged uploads")
def delete_upload_batch(batch_id: str):
    try:
        discard_batch(batch_id)
    except UploadValidationError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
