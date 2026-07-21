from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.database.models import MetadataIssue, Task
from app.database.session import get_db
from app.domain.task import TaskType
from app.services.library_health import HEALTH_ACTIONS, library_health
from app.services.task_service import cancel_task
from app.services.task_progress import get_typed_task, serialize_task_progress
from app.api.schemas.library import LibraryHealthResponse, TaskProgressResponse
from app.services.metadata_health import metadata_health, serialize_issue


router = APIRouter(prefix="/api/library/health", tags=["library", "health"])


def _metadata_error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


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


@router.post("/metadata/analyze", response_model=TaskProgressResponse, summary="Queue indexed metadata analysis")
def start_metadata_analysis(db: Session = Depends(get_db)):
    try:
        task = library_health.create_metadata_analysis(db)
    except ValueError as error:
        return _metadata_error(409, "conflicting_job", str(error))
    return serialize_task_progress(task)

@router.post("/metadata/songs/{song_id}/analyze")
def analyze_metadata_song(song_id: int, db: Session = Depends(get_db)):
    try: metadata_health.analyze_song(db, song_id); db.commit()
    except LookupError as error: return _metadata_error(404, "song_not_found", str(error))
    return {"items": [serialize_issue(x) for x in metadata_health.list(db, song_id=song_id, limit=200)[0]]}

@router.post("/metadata/albums/analyze")
def analyze_metadata_album(album_key: str, db: Session = Depends(get_db)):
    try: findings=metadata_health.analyze_album(db, album_key); db.commit()
    except LookupError as error: return _metadata_error(404, "album_not_found", str(error))
    return {"items":[serialize_issue(x) for x in metadata_health.list(db, entity_type="album", entity_id=album_key, limit=200)[0]]}

@router.post("/metadata/artists/analyze")
def analyze_metadata_artist(artist_key: str, db: Session = Depends(get_db)):
    try: findings=metadata_health.analyze_artist(db, artist_key); db.commit()
    except LookupError as error: return _metadata_error(404, "artist_not_found", str(error))
    return {"items":[serialize_issue(x) for x in metadata_health.list(db, entity_type="artist", entity_id=artist_key, limit=200)[0]]}

@router.get("/metadata/issues")
def list_metadata_issues(rule_id: str|None=None, severity: str|None=None, status: str|None=None, entity_type: str|None=None, field_name: str|None=None, song_id: int|None=None, album_key: str|None=None, artist_key: str|None=None, automatically_repairable: bool|None=None, search: str|None=None, first_detected_from:datetime|None=None, first_detected_to:datetime|None=None, last_detected_from:datetime|None=None, last_detected_to:datetime|None=None, limit:int=Query(50,ge=1,le=200), offset:int=Query(0,ge=0), db: Session=Depends(get_db)):
    items,total=metadata_health.list(db, rule_id=rule_id,severity=severity,status=status,entity_type=entity_type,field_name=field_name,song_id=song_id,album_key=album_key,artist_key=artist_key,automatically_repairable=automatically_repairable,search=search,first_detected_from=first_detected_from,first_detected_to=first_detected_to,last_detected_from=last_detected_from,last_detected_to=last_detected_to,limit=limit,offset=offset)
    return {"items":[serialize_issue(x) for x in items],"pagination":{"total":total,"limit":limit,"offset":offset,"has_more":offset+len(items)<total}}

@router.get("/metadata/issues/{issue_id}")
def metadata_issue(issue_id:int, db:Session=Depends(get_db)):
    issue=db.get(MetadataIssue,issue_id)
    if not issue: return _metadata_error(404, "issue_not_found", "Metadata issue not found")
    return serialize_issue(issue)

@router.post("/metadata/issues/{issue_id}/ignore")
def ignore_metadata_issue(issue_id:int, db:Session=Depends(get_db)):
    try: issue=metadata_health.set_status(db,issue_id,"ignored"); db.commit()
    except LookupError as error: return _metadata_error(404, "issue_not_found", str(error))
    return serialize_issue(issue)

@router.post("/metadata/issues/{issue_id}/restore")
def restore_metadata_issue(issue_id:int, db:Session=Depends(get_db)):
    try: issue=metadata_health.set_status(db,issue_id,"open"); db.commit()
    except LookupError as error: return _metadata_error(404, "issue_not_found", str(error))
    return serialize_issue(issue)

@router.post("/metadata/issues/{issue_id}/resolve")
def resolve_metadata_issue(issue_id:int, db:Session=Depends(get_db)):
    try: issue=metadata_health.resolve_verified(db,issue_id); db.commit()
    except LookupError as error: return _metadata_error(404, "issue_not_found", str(error))
    return serialize_issue(issue)

@router.get("/metadata/summary")
def metadata_summary(db:Session=Depends(get_db)):
    return metadata_health.summary(db)

@router.get("/metadata/score", summary="Get metadata health score and inputs")
def metadata_score(db:Session=Depends(get_db)):
    return metadata_health.score(db)

@router.get("/metadata/rules")
def metadata_rules():
    return {"items":[{"id":item.id,"scope":item.scope,"severity":item.severity,"version":item.version,
            "title":item.title,"explanation":item.explanation,"suggested_action":item.suggested_action}
            for item in metadata_health.rules.values()]}
