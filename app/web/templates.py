from fastapi.templating import Jinja2Templates

from app.core.config import get_settings

templates = Jinja2Templates(
    directory="app/templates",
)


settings = get_settings()


def template_context(**kwargs):
    return {
        "app_name": settings.app_name,
        "version": settings.app_version,
        "page": "",
        **kwargs,
    }