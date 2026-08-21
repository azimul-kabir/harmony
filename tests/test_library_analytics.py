from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.database.base import Base
from app.database.models import Song
from app.services.library_analytics import library_analytics
from app.main import app


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_library_summary_uses_available_index_rows_only():
    with _session() as db:
        db.add_all([
            Song(path="/music/a.mp3", filename="a.mp3", artist="Artist", album="Album", file_size=100, availability_status="available"),
            Song(path="/music/b.mp3", filename="b.mp3", artist="Artist", album="Album", file_size=200, availability_status="available"),
            Song(path="/music/missing.mp3", filename="missing.mp3", artist="Ignored", album="Ignored", file_size=999, availability_status="missing"),
        ])
        db.commit()

        assert library_analytics.calculate(db) == {
            "songs": 2,
            "albums": 1,
            "artists": 1,
            "storage_bytes": 300,
        }


def test_empty_library_summary_is_stable():
    with _session() as db:
        assert library_analytics.calculate(db) == {
            "songs": 0,
            "albums": 0,
            "artists": 0,
            "storage_bytes": 0,
        }


def test_library_analytics_api_is_not_part_of_v3_surface():
    assert TestClient(app).get("/api/library/analytics").status_code == 404
