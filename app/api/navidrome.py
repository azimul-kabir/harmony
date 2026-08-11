from fastapi import APIRouter, HTTPException, Query

from app.services.navidrome import NavidromeClient, NavidromeError
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
