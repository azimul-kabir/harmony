"""Password authentication for the web UI and API."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import Settings
from app.web.templates import templates

COOKIE_NAME = "harmony_session"
PUBLIC_PATHS = {"/login", "/health", "/health/live", "/health/ready"}


def _signing_key(settings: Settings) -> bytes:
    """Derive a session key so rotating the password revokes old sessions."""
    value = f"harmony-web-session:{settings.web_auth_username}:{settings.web_auth_password}"
    return hashlib.sha256(value.encode()).digest()


def create_session_token(settings: Settings, now: int | None = None) -> str:
    issued_at = str(now if now is not None else int(time.time()))
    signature = hmac.new(_signing_key(settings), issued_at.encode(), hashlib.sha256).digest()
    return f"{issued_at}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"


def valid_session_token(settings: Settings, token: str | None, now: int | None = None) -> bool:
    if not token or "." not in token:
        return False
    issued_at, supplied_signature = token.split(".", 1)
    try:
        timestamp = int(issued_at)
    except ValueError:
        return False
    current_time = now if now is not None else int(time.time())
    if timestamp > current_time + 60 or current_time - timestamp > settings.web_auth_session_hours * 3600:
        return False
    expected = create_session_token(settings, timestamp).split(".", 1)[1]
    return hmac.compare_digest(supplied_signature, expected)


def _safe_next(value: str | None) -> str:
    return value if value and value.startswith("/") and not value.startswith("//") else "/"


class AuthenticationMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next):
        # Opt-in avoids locking existing non-Compose installations out on upgrade.
        if not self.settings.web_auth_password:
            return await call_next(request)
        path = request.url.path
        if (
            path in PUBLIC_PATHS
            or path.startswith("/static/")
            or valid_session_token(self.settings, request.cookies.get(COOKIE_NAME))
        ):
            return await call_next(request)
        if path.startswith("/api/"):
            return JSONResponse(status_code=401, content={"detail": "Authentication required"})
        target = path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303)


def build_auth_router(settings: Settings) -> APIRouter:
    router = APIRouter(include_in_schema=False)

    @router.get("/login", response_class=HTMLResponse)
    def login_page(request: Request, next: str = "/"):
        if settings.web_auth_password and valid_session_token(settings, request.cookies.get(COOKIE_NAME)):
            return RedirectResponse(_safe_next(next), status_code=303)
        return templates.TemplateResponse("login.html", {
            "request": request, "next": _safe_next(next), "error": None,
            "auth_enabled": bool(settings.web_auth_password),
        })

    @router.post("/login")
    def login(request: Request, username: str = Form(...), password: str = Form(...), next: str = Form("/")):
        username_ok = hmac.compare_digest(username.encode(), settings.web_auth_username.encode())
        password_ok = bool(settings.web_auth_password) and hmac.compare_digest(
            password.encode(), settings.web_auth_password.encode()
        )
        if not (username_ok and password_ok):
            return templates.TemplateResponse("login.html", {
                "request": request, "next": _safe_next(next),
                "error": "Incorrect username or password.",
                "auth_enabled": bool(settings.web_auth_password),
            }, status_code=401)
        response = RedirectResponse(_safe_next(next), status_code=303)
        response.set_cookie(
            COOKIE_NAME, create_session_token(settings),
            max_age=settings.web_auth_session_hours * 3600,
            httponly=True, secure=settings.web_auth_secure_cookie,
            samesite="strict", path="/",
        )
        return response

    @router.post("/logout")
    def logout():
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(COOKIE_NAME, path="/")
        return response

    return router
