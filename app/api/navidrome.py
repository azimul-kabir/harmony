from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.core.config import get_settings
from app.database.models import Task
from app.database.session import SessionLocal
from app.services.navidrome import NavidromeClient, NavidromeError
from app.services.navidrome_love import create_job, public_job, run_job
from app.services.navidrome_sync_health import navidrome_sync_health

router = APIRouter(prefix="/api/navidrome", tags=["navidrome"])


def _http_error(error: NavidromeError):
    status = (
        401
        if error.code == "authentication_failed"
        else 503
        if error.code in {"navidrome_not_configured", "connection_failed", "timeout"}
        else 502
    )
    return HTTPException(
        status_code=status, detail={"code": error.code, "message": str(error)}
    )


@router.get("/status")
async def navidrome_status():
    return await NavidromeClient().status()


@router.get("/sync-health")
async def navidrome_health_status(refresh: bool = Query(default=False)):
    if refresh:
        return await navidrome_sync_health.check()
    return navidrome_sync_health.snapshot()


@router.post("/sync-health/reconcile")
async def reconcile_navidrome_health(full_scan: bool = Query(default=False)):
    return await navidrome_sync_health.reconcile(full_scan=full_scan)


@router.post("/rescan")
async def navidrome_rescan(full_scan: bool = Query(default=False)):
    try:
        return await NavidromeClient().start_scan(full_scan=full_scan)
    except NavidromeError as error:
        status_code = (
            503
            if error.code
            in {
                "navidrome_not_configured",
                "navidrome_unavailable",
            }
            else 502
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": error.code, "message": str(error)},
        ) from error


@router.post("/test")
async def test_navidrome_connection():
    try:
        result = await NavidromeClient().ping()
        return {"success": True, **result}
    except NavidromeError as error:
        raise _http_error(error) from error


@router.get("/playlists")
async def list_navidrome_playlists():
    try:
        items = await NavidromeClient().get_playlists()
        return {
            "playlists": [
                {
                    "id": str(item.get("id", "")),
                    "name": str(item.get("name") or "Untitled"),
                    "track_count": int(item.get("songCount") or 0),
                    "owner": item.get("owner"),
                }
                for item in items
                if item.get("id")
            ]
        }
    except NavidromeError as error:
        raise _http_error(error) from error


async def _start(playlist_id: str, operation: str, background: BackgroundTasks):
    if not get_settings().navidrome_love_enabled:
        raise HTTPException(
            403,
            detail={
                "code": "not_configured",
                "message": "Navidrome Love All is disabled.",
            },
        )
    try:
        playlists = await NavidromeClient().get_playlists()
        selected = next((p for p in playlists if str(p.get("id")) == playlist_id), None)
        if not selected:
            raise HTTPException(
                404,
                detail={
                    "code": "playlist_not_found",
                    "message": "The Navidrome playlist no longer exists.",
                },
            )
        task = create_job(
            playlist_id, str(selected.get("name") or "Untitled"), operation
        )
        background.add_task(run_job, task.id)
        return public_job(task)
    except ValueError as error:
        raise HTTPException(
            409, detail={"code": "duplicate_submission", "message": str(error)}
        ) from error
    except NavidromeError as error:
        raise _http_error(error) from error


@router.post("/playlists/{playlist_id}/love", status_code=202)
async def love_playlist(playlist_id: str, background: BackgroundTasks):
    return await _start(playlist_id, "love", background)


@router.post("/playlists/{playlist_id}/unlove", status_code=202)
async def unlove_playlist(playlist_id: str, background: BackgroundTasks):
    return await _start(playlist_id, "unlove", background)


@router.get("/jobs/{job_id}")
def get_love_job(job_id: int):
    db = SessionLocal()
    try:
        task = db.get(Task, job_id)
        if not task or task.task_type != "navidrome_love":
            raise HTTPException(
                404,
                detail={"code": "job_not_found", "message": "Navidrome job not found."},
            )
        return public_job(task)
    finally:
        db.close()
