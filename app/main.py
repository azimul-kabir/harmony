import threading
from app.api.tasks import router as tasks_router
from app.api.dashboard import router as dashboard_router
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.web.templates import (
    templates,
    template_context,
)

from app.api import downloads
from app.api.library import router as library_router
from app.api.playlist import router as playlist_router
from app.api.sync_sources import router as sync_sources_router
from app.core.config import get_settings
from app.core.logging import logger
from app.database.init_db import init_db
from app.workers.download_worker import worker_loop
from fastapi.staticfiles import StaticFiles
from app.database.session import SessionLocal
from app.services.dashboard import get_dashboard_stats
from app.web.downloads import router as downloads_page_router
from app.api.settings import router as settings_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(settings.download_path).mkdir(parents=True, exist_ok=True)
    Path(settings.staging_path).mkdir(parents=True, exist_ok=True)
    Path(settings.failed_path).mkdir(parents=True, exist_ok=True)

    init_db()

    thread = threading.Thread(
        target=worker_loop,
        daemon=True,
    )
    thread.start()

    logger.info("Harmony started")

    yield

    logger.info("Harmony stopped")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)


app.mount(
    "/static",
    StaticFiles(directory="app/static"),
    name="static",
)


app.include_router(tasks_router)
app.include_router(dashboard_router)
app.include_router(settings_router)
app.include_router(downloads_page_router)
app.include_router(library_router)
app.include_router(downloads.router)
app.include_router(playlist_router)
app.include_router(sync_sources_router)


@app.get("/")
def home(request: Request):
    db = SessionLocal()

    try:
        stats = get_dashboard_stats(db)

        return templates.TemplateResponse(
            "dashboard.html",
            template_context(
                request=request,
                stats=stats,
                page="dashboard",
            ),
        )

    finally:
        db.close()


@app.get("/health")
def health():
    return JSONResponse(
        {
            "status": "ok",
            "version": settings.app_version,
        }
    )