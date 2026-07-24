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
from app.api.metadata import router as metadata_router
from app.api.metadata_discovery import router as metadata_discovery_router
from app.api.navidrome import router as navidrome_router
from app.api.playlist import router as playlist_router
from app.api.settings import router as settings_router
from app.api.sync_sources import router as sync_sources_router
from app.api.tasks import router as tasks_router
from app.api.providers import router as providers_router
from app.core.config import get_settings
from app.core.logging import logger
from app.database.init_db import init_db
from app.database.session import SessionLocal
from app.services.dashboard import get_dashboard_snapshot
from app.services.library_watcher import LibraryWatcher
from app.services.library_bulk import library_bulk_worker
from app.services.library_health import library_maintenance_worker
from app.services.task_service import cleanup_library_jobs, recover_library_jobs
from app.services.metadata_intelligence import MetadataServiceError
from app.web.downloads import router as downloads_page_router
from app.web.library import router as library_page_router
from app.web.playlists import router as playlists_page_router
from app.web.sources import router as sources_page_router
from app.web.providers import router as providers_page_router
from app.providers.metadata.registry import close_providers
from app.web.templates import template_context, templates
from app.workers.download_worker import worker_loop
from app.services.settings_service import initialize_defaults
from app.services.download_processes import download_processes
from app.services.navidrome_playlist_sync import navidrome_playlist_reimport
from app.services.source_auto_sync import source_auto_sync_scheduler

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
        initialize_defaults(db)
        recover_library_jobs(db)
        cleanup_library_jobs(db)
    finally:
        db.close()
    library_bulk_worker.start()
    library_maintenance_worker.start()
    navidrome_playlist_reimport.start()
    source_auto_sync_scheduler.start()
    
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
        download_processes.begin_shutdown()
        library_bulk_worker.stop()
        library_maintenance_worker.stop()
        navidrome_playlist_reimport.stop()
        source_auto_sync_scheduler.stop()
        await close_providers()
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
app.include_router(metadata_router)
app.include_router(metadata_discovery_router)
app.include_router(navidrome_router)
app.include_router(artwork_router)
app.include_router(library_page_router)
app.include_router(downloads.router)
app.include_router(sources_page_router)
app.include_router(playlists_page_router)  # <-- Added the new Playlists route
app.include_router(playlist_router)
app.include_router(sync_sources_router)
app.include_router(providers_router)
app.include_router(providers_page_router)


@app.exception_handler(Exception)
async def unhandled_api_error_handler(request: Request, exc: Exception):
    """Never return Starlette's plain-text 500 response from an API route."""
    logger.exception("Unhandled request error for {}", request.url.path)
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Harmony could not complete this request. Please try again."}},
        )
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


@app.exception_handler(MetadataServiceError)
async def metadata_error_handler(request: Request, exc: MetadataServiceError):
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})

@app.get("/")
def home(request: Request):
    db = SessionLocal()
    try:
        snapshot = get_dashboard_snapshot(db)
        return templates.TemplateResponse(
            "dashboard.html",
            template_context(
                request=request,
                stats=snapshot["stats"],
                dashboard_snapshot=snapshot,
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
