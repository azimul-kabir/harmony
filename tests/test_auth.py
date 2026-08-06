from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.database.base import Base
from app.database.models import AuthSession, User
from app.web import auth
from app.web.auth import AuthenticationMiddleware, bootstrap_auth, build_auth_router, safe_next


@pytest.fixture
def auth_app(tmp_path: Path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'auth.db'}")
    local = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(auth, "SessionLocal", local)
    settings = Settings(auth_enabled=True, auth_bootstrap_username="Admin",
        auth_bootstrap_password="correct horse battery staple",
        auth_session_secret="s" * 48, auth_cookie_secure=True)
    bootstrap_auth(settings); bootstrap_auth(settings)
    app = FastAPI(); app.add_middleware(AuthenticationMiddleware, settings=settings)
    app.include_router(build_auth_router(settings))
    app.get("/")(lambda: {"ok": True})
    app.get("/api/private")(lambda: {"secret": True})
    app.get("/api/events")(lambda: {"event": True})
    app.get("/health")(lambda: {"status": "ok"})
    return app, local


def login(client: TestClient, password="correct horse battery staple"):
    page = client.get("/login")
    token = page.text.split('name="csrf_token" value="', 1)[1].split('"', 1)[0]
    return client.post("/login", data={"username": "ADMIN", "password": password,
        "next": "/", "csrf_token": token}, follow_redirects=False)


def test_rollout_defaults_disabled_and_enabled_validation():
    assert Settings().auth_enabled is False
    with pytest.raises(RuntimeError, match="32 bytes"):
        auth.resolved_secrets(Settings(auth_enabled=True))
    with pytest.raises(ValueError):
        Settings(auth_session_idle_minutes=0)


def test_secret_files_preserve_spaces_and_reject_ambiguity(tmp_path):
    secret = tmp_path / "secret"; secret.write_text(" " + "x" * 32 + " \r\n")
    _, value = auth.resolved_secrets(Settings(auth_enabled=True, auth_session_secret_file=str(secret)))
    assert value == " " + "x" * 32 + " "
    with pytest.raises(RuntimeError, match="only one"):
        auth.resolved_secrets(Settings(auth_enabled=True, auth_session_secret="x" * 32,
            auth_session_secret_file=str(secret)))


def test_bootstrap_hashes_password_and_is_idempotent(auth_app):
    _, local = auth_app
    with local() as db:
        users = db.scalars(select(User)).all()
        assert len(users) == 1 and users[0].username == "admin"
        assert "correct horse" not in users[0].password_hash
        assert auth.PASSWORD_HASHER.verify(users[0].password_hash, "correct horse battery staple")


def test_routes_login_random_sessions_logout_replay_and_csrf(auth_app):
    app, local = auth_app; client = TestClient(app, base_url="https://testserver")
    assert client.get("/", follow_redirects=False).status_code == 303
    assert client.get("/api/private").status_code == 401
    assert client.get("/health").status_code == 200
    first = login(client); assert first.status_code == 303
    cookie = client.cookies.get(auth.COOKIE_NAME)
    assert "HttpOnly" in first.headers["set-cookie"] and "Secure" in first.headers["set-cookie"]
    assert client.get("/").status_code == 200
    assert client.post("/logout").status_code == 403
    csrf = client.cookies.get(auth.CSRF_COOKIE_NAME)
    out = client.post("/logout", data={"csrf_token": csrf}, follow_redirects=False)
    assert out.status_code == 303 and "Clear-Site-Data" in out.headers
    client.cookies.set(auth.COOKIE_NAME, cookie)
    assert client.get("/", follow_redirects=False).status_code == 303
    with local() as db:
        sessions = db.scalars(select(AuthSession)).all()
        assert sessions[0].token_hash != cookie and sessions[0].revoked_at is not None


def test_distinct_logins_generic_failures_and_forwarded_spoof(auth_app):
    app, local = auth_app
    one = TestClient(app, base_url="https://testserver"); two = TestClient(app, base_url="https://testserver")
    assert login(one).status_code == login(two).status_code == 303
    assert one.cookies.get(auth.COOKIE_NAME) != two.cookies.get(auth.COOKIE_NAME)
    bad = TestClient(app, base_url="https://testserver")
    real = login(bad, "wrong password"); bad.cookies.clear(); missing_page = bad.get("/login")
    token = missing_page.text.split('name="csrf_token" value="', 1)[1].split('"', 1)[0]
    missing = bad.post("/login", data={"username": "nobody", "password": "wrong password", "csrf_token": token})
    assert real.status_code == missing.status_code == 401
    assert "Incorrect username or password." in real.text and "Incorrect username or password." in missing.text
    request = type("R", (), {"client": type("C", (), {"host": "socket"})(), "headers": {"x-forwarded-for": "spoof"}})()
    assert auth._client_address(request, Settings()) == "socket"
    with local() as db:
        assert len(db.scalars(select(AuthSession)).all()) == 2


@pytest.mark.parametrize("value", ["https://evil.test/", "//evil.test/", "/%2f%2fevil", "/\\evil", "/x\x00"])
def test_unsafe_return_paths_are_rejected(value):
    assert safe_next(value) == "/"
