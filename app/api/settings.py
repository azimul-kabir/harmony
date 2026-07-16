from fastapi import APIRouter, Request

from app.core.config import get_settings

from app.web.templates import (
    templates,
    template_context,
)

router = APIRouter(tags=["settings"])


@router.get("/settings")
def settings_page(request: Request):
    settings = get_settings()

    return templates.TemplateResponse(
        "settings.html",
        template_context(
            request=request,
            settings=settings,
            page="settings",
        ),
    )