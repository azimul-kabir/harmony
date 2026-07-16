from fastapi import APIRouter, Request

from app.web.templates import (
    template_context,
    templates,
)

router = APIRouter()


@router.get("/sources")
def sources_page(request: Request):
    return templates.TemplateResponse(
        "sources.html",
        template_context(
            request=request,
            page="sources",
        ),
    )