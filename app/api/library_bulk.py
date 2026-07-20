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


router = APIRouter(prefix="/api/library/bulk", tags=["library", "tasks"])


class BulkOperationRequest(BaseModel):
    operation: Literal[
        "delete",
        "move",
        "rename",
        "refresh_metadata",
        "refresh_artwork",
        "export",
    ]
    song_ids: list[int] = Field(min_length=1, max_length=5000)
    options: dict[str, str] = Field(default_factory=dict)


def _get_bulk_task(db: Session, task_id: int) -> Task:
    task = db.get(Task, task_id)
    if task is None or task.task_type != TaskType.LIBRARY_BULK.value:
        raise HTTPException(status_code=404, detail="Bulk task not found")
    return task


def serialize_bulk_task(db: Session, task: Task) -> dict:
    items = db.scalars(
        select(BulkOperationItem)
        .where(BulkOperationItem.task_id == task.id)
        .order_by(BulkOperationItem.id)
    ).all()
    processed = task.completed_items + task.failed_items + task.skipped_items
    return {
        "id": task.id,
        "name": task.name,
        "type": task.task_type,
        "status": task.status,
        "total": task.total_items,
        "completed": task.completed_items,
        "failed": task.failed_items,
        "skipped": task.skipped_items,
        "processed": processed,
        "progress": round((processed / task.total_items) * 100, 1) if task.total_items else 100,
        "current": task.current_item,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
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


@router.post("")
def start_bulk_operation(request: BulkOperationRequest, db: Session = Depends(get_db)):
    try:
        task = create_bulk_task(
            db,
            operation=request.operation,
            song_ids=request.song_ids,
            options=request.options,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return serialize_bulk_task(db, task)


@router.get("/{task_id}")
def get_bulk_operation(task_id: int, db: Session = Depends(get_db)):
    return serialize_bulk_task(db, _get_bulk_task(db, task_id))


@router.post("/{task_id}/cancel")
def cancel_bulk_operation(task_id: int, db: Session = Depends(get_db)):
    task = _get_bulk_task(db, task_id)
    cancel_task(db, task)
    return serialize_bulk_task(db, task)


@router.get("/{task_id}/export")
def download_bulk_export(task_id: int, db: Session = Depends(get_db)):
    task = _get_bulk_task(db, task_id)
    if task.status not in {TaskStatus.COMPLETED.value, TaskStatus.FAILED.value}:
        raise HTTPException(status_code=409, detail="Export is not finished")
    if not task.output_path or not Path(task.output_path).is_file():
        raise HTTPException(status_code=404, detail="Export file not found")
    return FileResponse(
        task.output_path,
        media_type="application/zip",
        filename=Path(task.output_path).name,
    )
