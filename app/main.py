import threading

from contextlib import asynccontextmanager

from app.workers.download_worker import worker_loop

from pathlib import Path

from app.api import downloads

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from app.api.playlist import router as playlist_router

from app.core.config import get_settings
from app.core.logging import logger
from app.database.init_db import init_db

from app.api.library import router as library_router

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

app.include_router(library_router)

app.include_router(downloads.router)

app.include_router(playlist_router)

templates = Jinja2Templates(directory="app/templates")


@app.get("/")
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "app_name": settings.app_name,
            "version": settings.app_version,
            "music_path": settings.music_path,
            "download_path": settings.download_path,
        },
    )


@app.get("/health")
def health():
    return JSONResponse(
        {
            "status": "ok",
            "version": settings.app_version,
        }
    )
