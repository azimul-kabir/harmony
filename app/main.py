import threading
from app.web.settings import router as settings_page_router
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import downloads, library
from app.api.artwork import router as artwork_router
from app.api.dashboard import router as dashboard_router
from app.api.library import router as library_router
from app.api.library_bulk import router as library_bulk_router
from app.api.library_health import router as library_health_router
from app.api.playlist import router as playlist_router
from app.api.settings import router as settings_router
from app.api.sync_sources import router as sync_sources_router
from app.api.tasks import router as tasks_router
from app.core.config import get_settings
from app.core.logging import logger
from app.database.init_db import init_db
from app.database.session import SessionLocal
from app.services.dashboard import get_dashboard_stats
from app.services.library_watcher import LibraryWatcher
from app.services.library_bulk import library_bulk_worker
from app.services.library_health import library_maintenance_worker
from app.services.task_service import cleanup_library_jobs, recover_library_jobs
from app.web.downloads import router as downloads_page_router
from app.web.library import router as library_page_router
from app.web.playlists import router as playlists_page_router
from app.web.sources import router as sources_page_router
from app.web.templates import template_context, templates
from app.workers.download_worker import worker_loop

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(settings.download_path).mkdir(parents=True, exist_ok=True)
    Path(settings.staging_path).mkdir(parents=True, exist_ok=True)
    Path(settings.failed_path).mkdir(parents=True, exist_ok=True)
    Path(settings.music_path).mkdir(parents=True, exist_ok=True)
    Path(settings.artwork_cache_path).mkdir(parents=True, exist_ok=True)
    init_db()
    db = SessionLocal()
    try:
        recover_library_jobs(db)
        cleanup_library_jobs(db)
    finally:
        db.close()
    library_bulk_worker.start()
    library_maintenance_worker.start()
    
    logger.info("Starting Harmony...")
    logger.info(
        "Starting {} download workers...",
        settings.max_parallel_downloads,
    )
    for i in range(settings.max_parallel_downloads):
        threading.Thread(
            target=worker_loop,
            daemon=True,
            name=f"download-worker-{i + 1}",
        ).start()
        
    library_watcher = None
    if settings.library_watcher_enabled:
        library_watcher = LibraryWatcher(
            root=settings.music_path,
            debounce_seconds=settings.library_watcher_debounce_seconds,
        )
        library_watcher.start()
        app.state.library_watcher = library_watcher

    logger.info("Harmony started")
    try:
        yield
    finally:
        library_bulk_worker.stop()
        library_maintenance_worker.stop()
        if library_watcher is not None:
            library_watcher.stop()
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
app.include_router(settings_page_router)  # The /settings HTML Web page (app/web/settings.py)
app.include_router(downloads_page_router)
app.include_router(library_router)
app.include_router(library_bulk_router)
app.include_router(library_health_router)
app.include_router(artwork_router)
app.include_router(library_page_router)
app.include_router(downloads.router)
app.include_router(sources_page_router)
app.include_router(playlists_page_router)  # <-- Added the new Playlists route
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
