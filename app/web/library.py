from fastapi import APIRouter, Request
from app.web.templates import templates, template_context

# This variable 'router' must exist in this file
router = APIRouter(tags=["web"])

@router.get("/library")
def library_page(request: Request):
    return templates.TemplateResponse(
        "library.html",
        template_context(request=request, page="library"),
    )


@router.get("/library/health")
def library_health_page(request: Request):
    return templates.TemplateResponse(
        "library_health.html",
        template_context(request=request, page="library"),
    )
