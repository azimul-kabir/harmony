import asyncio

from fastapi import APIRouter, HTTPException, Query

from app.services.navidrome import NavidromeClient, NavidromeError
from app.services.navidrome_id_reconciliation import navidrome_id_reconciler

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


@router.get("/id-reconciliation")
async def navidrome_id_reconciliation_status():
    """Return the last persisted Navidrome ID reconciliation summary."""
    return await asyncio.to_thread(navidrome_id_reconciler.last_result)


@router.post("/id-reconciliation")
async def reconcile_navidrome_ids():
    """Refresh persisted Navidrome song and playlist IDs from the live catalog."""
    result = await navidrome_id_reconciler.reconcile(trigger="manual")
    status_code = {
        "unconfigured": 503,
        "unavailable": 503,
        "busy": 409,
        "scanning": 409,
        "failed": 502,
    }.get(result["state"])
    if status_code is not None:
        messages = {
            "unconfigured": "Navidrome credentials are not configured.",
            "unavailable": result.get("error") or "Harmony could not reach Navidrome.",
            "busy": "Navidrome ID reconciliation is already running.",
            "scanning": "Navidrome is scanning; try again when the scan finishes.",
            "failed": result.get("error") or "Navidrome ID reconciliation failed.",
        }
        raise HTTPException(
            status_code=status_code,
            detail={"code": f"navidrome_ids_{result['state']}", "message": messages[result["state"]]},
        )
    return result
