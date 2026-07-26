"""Container-friendly liveness and readiness probes."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.database.session import SessionLocal


router = APIRouter(tags=["health"])


def _database_check() -> dict[str, str]:
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        revision = db.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        return {"status": "ok", "revision": revision}
    finally:
        db.close()


def _storage_check(path: str) -> dict[str, str]:
    target = Path(path)
    if not target.is_dir():
        raise RuntimeError("directory_missing")
    if not os.access(target, os.R_OK | os.W_OK | os.X_OK):
        raise RuntimeError("directory_not_writable")
    return {"status": "ok"}


def readiness_snapshot() -> tuple[dict, int]:
    settings = get_settings()
    checks: dict[str, dict[str, str]] = {}

    try:
        checks["database"] = _database_check()
    except Exception:
        checks["database"] = {"status": "error", "reason": "unavailable"}

    for name, path in (
        ("music", settings.music_path),
        ("downloads", settings.download_path),
        ("staging", settings.staging_path),
        ("failed", settings.failed_path),
        ("artwork_cache", settings.artwork_cache_path),
    ):
        try:
            checks[name] = _storage_check(path)
        except RuntimeError as error:
            checks[name] = {"status": "error", "reason": str(error)}
        except OSError:
            checks[name] = {"status": "error", "reason": "unavailable"}

    ready = all(check["status"] == "ok" for check in checks.values())
    payload = {
        "status": "ok" if ready else "not_ready",
        "version": settings.app_version,
        "checks": checks,
    }
    return payload, 200 if ready else 503


@router.get("/health", include_in_schema=False)
@router.get("/health/live", summary="Check whether the Harmony process is alive")
def liveness():
    settings = get_settings()
    return {"status": "ok", "version": settings.app_version}


@router.get("/health/ready", summary="Check database and required storage readiness")
def readiness():
    payload, status_code = readiness_snapshot()
    return JSONResponse(status_code=status_code, content=payload)
