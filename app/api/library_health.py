from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database.models import Task
from app.database.session import get_db
from app.domain.task import TaskType
from app.services.library_health import HEALTH_ACTIONS, library_health
from app.services.task_service import cancel_task
from app.services.task_progress import get_typed_task, serialize_task_progress
from app.api.schemas.library import LibraryHealthIssuesResponse, LibraryHealthResponse, TaskProgressResponse


router = APIRouter(prefix="/api/library/health", tags=["library", "health"])


def _get_task(db: Session, task_id: int) -> Task:
    task = get_typed_task(db, task_id, TaskType.LIBRARY_MAINTENANCE)
    if task is None:
        raise HTTPException(status_code=404, detail="Library maintenance task not found")
    return task


@router.get(
    "",
    response_model=LibraryHealthResponse,
    summary="Get Library health",
    description="Returns index-only completeness metrics and registered health checks.",
)
def health_snapshot(db: Session = Depends(get_db)):
    return library_health.calculate(db)


@router.get("/issues/{check_id}", response_model=LibraryHealthIssuesResponse, summary="List actionable Library health issues")
def health_issues(check_id: str, db: Session = Depends(get_db), limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0)):
    try:
        return library_health.issues(db, check_id, limit, offset)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/issues/{issue_id}/discover", summary="Discover metadata candidates without changing a song")
def discover_issue_match(issue_id: str):
    # No metadata-provider candidate API is configured in Harmony yet.  This endpoint
    # deliberately does not download, mutate tags, or expose an opaque internal ID.
    return {"outcome": "provider_unavailable", "message": "Metadata lookup is temporarily unavailable. No song metadata was changed."}


@router.post(
    "/actions/{action}",
    response_model=TaskProgressResponse,
    summary="Queue Library maintenance",
    description="Queues refresh, rebuild, verification, or artwork-cache maintenance as a durable task.",
)
def start_health_action(action: str, db: Session = Depends(get_db)):
    if action not in HEALTH_ACTIONS:
        raise HTTPException(status_code=404, detail="Library health action not found")
    try:
        task = library_health.create_action(db, action)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return serialize_task_progress(task)


@router.get("/tasks/{task_id}", response_model=TaskProgressResponse, summary="Get maintenance progress")
def health_task(task_id: int, db: Session = Depends(get_db)):
    return serialize_task_progress(_get_task(db, task_id))


@router.post("/tasks/{task_id}/cancel", response_model=TaskProgressResponse, summary="Cancel maintenance")
def cancel_health_task(task_id: int, db: Session = Depends(get_db)):
    task = _get_task(db, task_id)
    cancel_task(db, task)
    return serialize_task_progress(task)
