from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.core.logging import logger
from app.database.init_db import init_db

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
)

templates = Jinja2Templates(directory="app/templates")


@app.on_event("startup")
def startup() -> None:
    Path(settings.download_path).mkdir(parents=True, exist_ok=True)
    Path(settings.staging_path).mkdir(parents=True, exist_ok=True)
    Path(settings.failed_path).mkdir(parents=True, exist_ok=True)

    init_db()

    logger.info("Harmony started")


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