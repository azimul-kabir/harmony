"""Database-backed local authentication, CSRF protection, and throttling."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import OrderedDict, deque
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, select
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import Settings
from app.core.logging import logger
from app.core.time import utcnow_naive
from app.database.models import AuthSession, User
from app.database.session import SessionLocal
from app.web.templates import templates

COOKIE_NAME = "harmony_session"
CSRF_COOKIE_NAME = "harmony_csrf"
PREAUTH_COOKIE_NAME = "harmony_login_csrf"
PUBLIC_PATHS = {"/login", "/health", "/health/live", "/health/ready", "/manifest.webmanifest", "/service-worker.js"}
PASSWORD_MIN_LENGTH = 12
PASSWORD_HASHER = PasswordHasher()
DUMMY_HASH = PASSWORD_HASHER.hash("dummy-password-never-used")


def normalize_username(value: str) -> str:
    return value.casefold()


def _read_secret(direct: str, filename: str, label: str) -> str:
    if direct and filename:
        raise RuntimeError(f"Set only one of {label} or {label}_FILE")
    if filename:
        try:
            return Path(filename).read_text(encoding="utf-8").rstrip("\r\n")
        except OSError as exc:
            raise RuntimeError(f"{label}_FILE cannot be read") from exc
    return direct


def resolved_secrets(settings: Settings) -> tuple[str, str]:
    password = _read_secret(settings.auth_bootstrap_password, settings.auth_bootstrap_password_file, "AUTH_BOOTSTRAP_PASSWORD")
    secret = _read_secret(settings.auth_session_secret, settings.auth_session_secret_file, "AUTH_SESSION_SECRET")
    if settings.auth_enabled and len(secret.encode()) < 32:
        raise RuntimeError("AUTH_SESSION_SECRET must contain at least 32 bytes")
    if password and len(password) < PASSWORD_MIN_LENGTH:
        raise RuntimeError(f"AUTH_BOOTSTRAP_PASSWORD must be at least {PASSWORD_MIN_LENGTH} characters")
    return password, secret


def token_digest(secret: str, token: str) -> str:
    return hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()


def bootstrap_auth(settings: Settings) -> None:
    """Validate enabled mode and transactionally create the first admin."""
    if not settings.auth_enabled:
        if settings.web_auth_password:
            logger.warning("WEB_AUTH_* is deprecated and ignored; migrate using AUTH_* settings")
        return
    password, _ = resolved_secrets(settings)
    username = normalize_username(settings.auth_bootstrap_username)
    if not username or len(username) > 128:
        raise RuntimeError("AUTH_BOOTSTRAP_USERNAME must contain 1 to 128 characters")
    db = SessionLocal()
    try:
        count = db.scalar(select(func.count()).select_from(User)) or 0
        if count:
            if password:
                logger.warning("Bootstrap password is still configured; remove it now that a user exists")
            return
        if not password:
            raise RuntimeError("Authentication is enabled but no users exist; configure AUTH_BOOTSTRAP_PASSWORD[_FILE]")
        now = utcnow_naive()
        db.add(User(username=username, password_hash=PASSWORD_HASHER.hash(password), is_active=True,
                    is_admin=True, session_version=1, created_at=now, updated_at=now))
        db.commit()
        logger.info("Created the first Harmony administrator")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def safe_next(value: str | None) -> str:
    if not value or any(ord(c) < 32 for c in value) or "\\" in value:
        return "/"
    try:
        decoded = unquote(value)
        parsed = urlsplit(decoded)
    except ValueError:
        return "/"
    if parsed.scheme or parsed.netloc or not decoded.startswith("/") or decoded.startswith("//") or "\\" in decoded:
        return "/"
    return decoded


class LoginLimiter:
    def __init__(self, maximum: int = 2048, attempts: int = 5, window: int = 300):
        self.maximum, self.attempts, self.window = maximum, attempts, window
        self.data: OrderedDict[str, deque[float]] = OrderedDict()
        self.lock = threading.Lock()

    def retry_after(self, keys: tuple[str, str], now: float | None = None) -> int:
        now = now or time.monotonic()
        with self.lock:
            retry = 0
            for key in keys:
                bucket = self.data.get(key, deque())
                while bucket and now - bucket[0] >= self.window:
                    bucket.popleft()
                if len(bucket) >= self.attempts:
                    retry = max(retry, int(self.window - (now - bucket[0])) + 1)
            return retry

    def failure(self, keys: tuple[str, str], now: float | None = None) -> None:
        now = now or time.monotonic()
        with self.lock:
            for key in keys:
                bucket = self.data.setdefault(key, deque())
                bucket.append(now)
                self.data.move_to_end(key)
            while len(self.data) > self.maximum:
                self.data.popitem(last=False)

    def success(self, keys: tuple[str, str]) -> None:
        with self.lock:
            for key in keys:
                self.data.pop(key, None)


LOGIN_LIMITER = LoginLimiter()


def _client_address(request: Request, settings: Settings) -> str:
    direct = request.client.host if request.client else "unknown"
    trusted = {item.strip() for item in settings.auth_trusted_proxies.split(",") if item.strip()}
    if direct in trusted:
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        if forwarded:
            return forwarded
    return direct


def _preauth_token(secret: str) -> str:
    raw = secrets.token_urlsafe(32)
    return f"{raw}.{token_digest(secret, raw)}"


def _valid_preauth(secret: str, token: str | None, supplied: str | None) -> bool:
    if not token or not supplied or "." not in token:
        return False
    raw, signature = token.rsplit(".", 1)
    return hmac.compare_digest(raw, supplied) and hmac.compare_digest(signature, token_digest(secret, raw))


def _load_session(settings: Settings, bearer: str | None) -> tuple[AuthSession, User] | None:
    if not bearer:
        return None
    _, secret = resolved_secrets(settings)
    digest = token_digest(secret, bearer)
    db = SessionLocal()
    try:
        session = db.scalar(select(AuthSession).where(AuthSession.token_hash == digest))
        now = utcnow_naive()
        if not session or session.revoked_at or session.expires_at <= now:
            return None
        user = session.user
        if not user or not user.is_active or user.session_version != session.session_version:
            return None
        if session.last_seen_at + timedelta(minutes=settings.auth_session_idle_minutes) <= now:
            return None
        if session.last_seen_at + timedelta(minutes=5) <= now:
            session.last_seen_at = now
            db.commit()
        db.expunge(session); db.expunge(user)
        return session, user
    finally:
        db.close()


class AuthenticationMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings):
        super().__init__(app); self.settings = settings

    async def dispatch(self, request: Request, call_next):
        if not self.settings.auth_enabled:
            return await call_next(request)
        path = request.url.path
        public = path in PUBLIC_PATHS or path.startswith("/static/")
        loaded = _load_session(self.settings, request.cookies.get(COOKIE_NAME))
        request.state.auth_user = loaded[1] if loaded else None
        request.state.auth_session = loaded[0] if loaded else None
        if not public and not loaded:
            if path.startswith("/api/") or request.headers.get("accept", "").startswith("text/event-stream"):
                return JSONResponse({"detail": "Authentication required"}, status_code=401, headers={"Cache-Control": "no-store"})
            target = path + (f"?{request.url.query}" if request.url.query else "")
            return RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303, headers={"Cache-Control": "no-store"})
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            supplied = request.headers.get("x-csrf-token")
            if not supplied and request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
                # BaseHTTPMiddleware must replay a consumed body for FastAPI's
                # downstream form parser.
                body = await request.body()
                supplied = parse_qs(body.decode("utf-8", "replace")).get("csrf_token", [None])[0]
                sent = False
                async def replay():
                    nonlocal sent
                    if sent:
                        return {"type": "http.request", "body": b"", "more_body": False}
                    sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                request._receive = replay
            _, secret = resolved_secrets(self.settings)
            valid = (_valid_preauth(secret, request.cookies.get(PREAUTH_COOKIE_NAME), supplied) if path == "/login"
                     else bool(loaded and supplied and hmac.compare_digest(loaded[0].csrf_token_hash, token_digest(secret, supplied))))
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                valid = False
            if not valid:
                return JSONResponse({"detail": "CSRF validation failed"}, status_code=403, headers={"Cache-Control": "no-store"})
        response = await call_next(request)
        if loaded or path == "/login":
            response.headers["Cache-Control"] = "no-store"
        return response


def build_auth_router(settings: Settings) -> APIRouter:
    router = APIRouter(include_in_schema=False)

    @router.get("/login", response_class=HTMLResponse)
    def login_page(request: Request, next: str = "/"):
        _, secret = resolved_secrets(settings)
        token = _preauth_token(secret)
        raw = token.split(".", 1)[0]
        response = templates.TemplateResponse("login.html", {"request": request, "next": safe_next(next), "error": None,
            "username": "", "csrf_token": raw, "auth_enabled": settings.auth_enabled})
        response.set_cookie(PREAUTH_COOKIE_NAME, token, httponly=True, secure=settings.auth_cookie_secure,
                            samesite=settings.auth_cookie_samesite, path="/", max_age=600)
        response.headers["Cache-Control"] = "no-store"
        return response

    @router.post("/login")
    def login(request: Request, username: str = Form(...), password: str = Form(...), next: str = Form("/"), csrf_token: str = Form(...)):
        normalized = normalize_username(username)
        address = _client_address(request, settings)
        keys = (f"u:{normalized}", f"a:{address}")
        retry = LOGIN_LIMITER.retry_after(keys)
        if retry:
            return templates.TemplateResponse("login.html", {"request": request, "next": safe_next(next), "error": "Too many attempts. Try again later.",
                "username": username, "csrf_token": csrf_token, "auth_enabled": True}, status_code=429, headers={"Retry-After": str(retry), "Cache-Control": "no-store"})
        db = SessionLocal()
        try:
            user = db.scalar(select(User).where(User.username == normalized))
            encoded = user.password_hash if user else DUMMY_HASH
            try: PASSWORD_HASHER.verify(encoded, password); password_ok = True
            except (VerifyMismatchError, VerificationError, InvalidHashError): password_ok = False
            if not user or not user.is_active or not password_ok:
                LOGIN_LIMITER.failure(keys)
                return templates.TemplateResponse("login.html", {"request": request, "next": safe_next(next), "error": "Incorrect username or password.",
                    "username": username, "csrf_token": csrf_token, "auth_enabled": True}, status_code=401, headers={"Cache-Control": "no-store"})
            if PASSWORD_HASHER.check_needs_rehash(user.password_hash):
                user.password_hash = PASSWORD_HASHER.hash(password)
            raw, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
            _, secret = resolved_secrets(settings); now = utcnow_naive()
            db.add(AuthSession(user_id=user.id, token_hash=token_digest(secret, raw), csrf_token_hash=token_digest(secret, csrf),
                session_version=user.session_version, created_at=now, last_seen_at=now,
                expires_at=now + timedelta(hours=settings.auth_session_absolute_hours)))
            user.last_login_at = now; user.updated_at = now; db.commit(); LOGIN_LIMITER.success(keys)
        finally:
            db.close()
        response = RedirectResponse(safe_next(next), status_code=303, headers={"Cache-Control": "no-store"})
        maximum = settings.auth_session_absolute_hours * 3600
        for name, value, http_only in ((COOKIE_NAME, raw, True), (CSRF_COOKIE_NAME, csrf, False)):
            response.set_cookie(name, value, max_age=maximum, httponly=http_only, secure=settings.auth_cookie_secure,
                                samesite=settings.auth_cookie_samesite, path="/")
        response.delete_cookie(PREAUTH_COOKIE_NAME, path="/", secure=settings.auth_cookie_secure, samesite=settings.auth_cookie_samesite)
        return response

    @router.post("/logout")
    def logout(request: Request):
        db = SessionLocal()
        try:
            session = db.get(AuthSession, request.state.auth_session.id)
            if session: session.revoked_at = utcnow_naive(); db.commit()
        finally: db.close()
        response = RedirectResponse("/login", status_code=303, headers={"Cache-Control": "no-store", "Clear-Site-Data": '"cache"'})
        for name in (COOKIE_NAME, CSRF_COOKIE_NAME):
            response.delete_cookie(name, path="/", secure=settings.auth_cookie_secure, samesite=settings.auth_cookie_samesite)
        return response

    return router
