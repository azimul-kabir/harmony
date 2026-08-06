from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.web.auth import AuthenticationMiddleware, build_auth_router


def authenticated_app() -> FastAPI:
    settings = Settings(web_auth_username="listener", web_auth_password="correct horse battery staple")
    test_app = FastAPI()
    test_app.add_middleware(AuthenticationMiddleware, settings=settings)
    test_app.include_router(build_auth_router(settings))

    @test_app.get("/")
    def home():
        return {"ok": True}

    @test_app.get("/api/private")
    def private_api():
        return {"secret": True}

    @test_app.get("/health")
    def health():
        return {"status": "ok"}

    return test_app


def test_web_pages_redirect_to_login_and_preserve_destination():
    response = TestClient(authenticated_app()).get("/?view=recent", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=%2F%3Fview%3Drecent"


def test_api_returns_json_unauthorized_and_health_stays_public():
    client = TestClient(authenticated_app())
    assert client.get("/api/private").status_code == 401
    assert client.get("/health").status_code == 200


def test_login_sets_hardened_cookie_and_logout_revokes_it():
    client = TestClient(authenticated_app())
    response = client.post("/login", data={
        "username": "listener", "password": "correct horse battery staple", "next": "/",
    }, follow_redirects=False)
    assert response.status_code == 303
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    assert client.get("/").status_code == 200
    client.post("/logout", follow_redirects=False)
    assert client.get("/", follow_redirects=False).status_code == 303


def test_bad_credentials_do_not_create_session():
    response = TestClient(authenticated_app()).post(
        "/login", data={"username": "listener", "password": "wrong"}
    )
    assert response.status_code == 401
    assert "Incorrect username or password" in response.text
