import secrets
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import Settings
from app.core.logging import logger
from app.web.templates import templates

router = APIRouter(include_in_schema=False)

PUBLIC_PATHS = {
    "/login",
    "/health",
    "/health/live",
    "/health/ready",
    "/manifest.webmanifest",
    "/service-worker.js",
}


def _safe_next(value: str | None) -> str:
    """Only permit same-origin absolute paths after authentication."""
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return "/"


class AuthenticationMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if (
            not self.settings.web_auth_enabled
            or path in PUBLIC_PATHS
            or path.startswith("/static/")
            or request.session.get("authenticated") is True
        ):
            return await call_next(request)

        if path.startswith("/api/"):
            return JSONResponse(
                {"error": {"code": "authentication_required", "message": "Sign in to Harmony to continue."}},
                status_code=401,
            )

        target = _safe_next(path + (f"?{request.url.query}" if request.url.query else ""))
        return RedirectResponse(url=f"/login?next={quote(target, safe='')}", status_code=303)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/"):
    if request.session.get("authenticated") is True:
        return RedirectResponse(_safe_next(next), status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": None,
            "next": _safe_next(next),
            "version": request.app.state.settings.app_version,
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post("/login", response_class=HTMLResponse)
async def login(request: Request):
    settings = request.app.state.settings
    values = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    username = values.get("username", [""])[0]
    password = values.get("password", [""])[0]
    next_path = _safe_next(values.get("next", ["/"])[0])

    configured = bool(settings.web_auth_username and settings.web_auth_password)
    valid = configured and secrets.compare_digest(username, settings.web_auth_username)
    valid = valid and secrets.compare_digest(password, settings.web_auth_password)
    if valid:
        request.session.clear()
        request.session["authenticated"] = True
        return RedirectResponse(next_path, status_code=303)

    if not configured:
        logger.error("Web authentication is enabled but WEB_AUTH_USERNAME or WEB_AUTH_PASSWORD is empty")
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": "Harmony authentication is not configured." if not configured else "Incorrect username or password.",
            "next": next_path,
            "version": settings.app_version,
        },
        status_code=503 if not configured else 401,
        headers={"Cache-Control": "no-store"},
    )


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
