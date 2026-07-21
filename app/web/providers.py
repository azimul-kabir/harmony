from fastapi import APIRouter, Request

from app.web.templates import template_context, templates

router = APIRouter(tags=["web", "development"])


@router.get("/developers/providers")
def provider_diagnostics_page(request: Request):
    return templates.TemplateResponse("provider_diagnostics.html", template_context(request=request, page="providers"))
