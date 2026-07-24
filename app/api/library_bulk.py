from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import BulkOperationItem, Task
from app.database.session import get_db
from app.domain.task import TaskStatus, TaskType
from app.services.library_bulk import create_bulk_task
from app.services.task_service import cancel_task
from app.services.task_progress import get_typed_task, serialize_task_progress
from app.api.schemas.library import BulkTaskResponse


router = APIRouter(prefix="/api/library/bulk", tags=["library", "tasks"])


class BulkOperationRequest(BaseModel):
    operation: Literal[
        "delete",
        "forget_missing",
        "move",
        "rename",
        "refresh_metadata",
        "refresh_artwork",
        "fetch_artwork",
        "export",
    ]
    song_ids: list[int] = Field(min_length=1, max_length=5000)
    options: dict[str, str] = Field(default_factory=dict)


def _get_bulk_task(db: Session, task_id: int) -> Task:
    task = get_typed_task(db, task_id, TaskType.LIBRARY_BULK)
    if task is None:
        raise HTTPException(status_code=404, detail="Bulk task not found")
    return task


def serialize_bulk_task(db: Session, task: Task) -> dict:
    items = db.scalars(
        select(BulkOperationItem)
        .where(BulkOperationItem.task_id == task.id)
        .order_by(BulkOperationItem.id)
    ).all()
    return {
        **serialize_task_progress(task),
        "download_url": f"/api/library/bulk/{task.id}/export" if task.output_path else None,
        "items": [
            {
                "id": item.id,
                "song_id": item.song_id,
                "original_path": item.original_path,
                "result_path": item.result_path,
                "status": item.status,
                "error": item.error,
            }
            for item in items
        ],
    }


@router.post(
    "",
    response_model=BulkTaskResponse,
    summary="Queue a Library bulk operation",
    description="Creates a durable asynchronous task with one independently recoverable item per Song.",
)
def start_bulk_operation(request: BulkOperationRequest, db: Session = Depends(get_db)):
    try:
        task = create_bulk_task(
            db,
            operation=request.operation,
            song_ids=request.song_ids,
            options=request.options,
        )
    except ValueError as error:
        raise HTTPException(status_code=409 if str(error).startswith("CONFLICTING_JOB") else 400, detail=str(error)) from error
    return serialize_bulk_task(db, task)


@router.get("/{task_id}", response_model=BulkTaskResponse, summary="Get bulk-operation progress")
def get_bulk_operation(task_id: int, db: Session = Depends(get_db)):
    return serialize_bulk_task(db, _get_bulk_task(db, task_id))


@router.post("/{task_id}/cancel", response_model=BulkTaskResponse, summary="Cancel a bulk operation")
def cancel_bulk_operation(task_id: int, db: Session = Depends(get_db)):
    task = _get_bulk_task(db, task_id)
    cancel_task(db, task)
    return serialize_bulk_task(db, task)


@router.get("/{task_id}/export", summary="Download a completed Library export")
def download_bulk_export(task_id: int, db: Session = Depends(get_db)):
    task = _get_bulk_task(db, task_id)
    if task.status not in {TaskStatus.COMPLETED.value, TaskStatus.COMPLETED_WITH_ERRORS.value}:
        raise HTTPException(status_code=409, detail="Export is not finished")
    if not task.output_path or not Path(task.output_path).is_file():
        raise HTTPException(status_code=404, detail="Export file not found")
    return FileResponse(
        task.output_path,
        media_type="application/zip",
        filename=Path(task.output_path).name,
    )
