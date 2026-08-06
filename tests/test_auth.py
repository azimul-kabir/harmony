from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.web.auth import _safe_next


def test_safe_next_rejects_external_redirects():
    assert _safe_next("//example.com/steal") == "/"
    assert _safe_next("https://example.com/steal") == "/"
    assert _safe_next("/downloads?state=active") == "/downloads?state=active"


def test_login_and_logout_flow(monkeypatch):
    auth = Settings(
        auth_enabled=True,
        auth_username="owner",
        auth_password="correct horse battery staple",
        auth_session_secret="test-only-session-secret",
    )
    runtime_settings = app.state.settings
    monkeypatch.setattr(runtime_settings, "auth_enabled", True)
    monkeypatch.setattr(runtime_settings, "auth_username", auth.auth_username)
    monkeypatch.setattr(runtime_settings, "auth_password", auth.auth_password)
    monkeypatch.setattr(runtime_settings, "auth_session_secret", auth.auth_session_secret)

    client = TestClient(app)
    protected = client.get("/downloads", follow_redirects=False)
    assert protected.status_code == 303
    assert protected.headers["location"].startswith("/login?next=")

    denied = client.get("/api/downloads")
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "authentication_required"

    invalid = client.post("/login", data={"username": "owner", "password": "wrong"})
    assert invalid.status_code == 401

    signed_in = client.post(
        "/login",
        data={"username": "owner", "password": auth.auth_password, "next": "/downloads"},
        follow_redirects=False,
    )
    assert signed_in.status_code == 303
    assert signed_in.headers["location"] == "/downloads"
    assert client.get("/downloads").status_code == 200

    signed_out = client.post("/logout", follow_redirects=False)
    assert signed_out.status_code == 303
    assert client.get("/downloads", follow_redirects=False).status_code == 303
