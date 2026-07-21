from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database.base import Base
from app.database.models import Song
from app.services.library_analytics import library_analytics


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_library_analytics_use_available_index_rows_only():
    now = datetime.now(UTC).replace(tzinfo=None)
    old = now - timedelta(days=30)
    with _session() as db:
        db.add_all(
            [
                Song(
                    path="/music/a1.flac", filename="a1.flac", title="A1",
                    artist="Artist One", album_artist="Artist One", album="Album A",
                    genre="Rock", year=1990, bitrate=1000000, duration=200,
                    file_size=1000, created_at=old, availability_status="available",
                ),
                Song(
                    path="/music/a2.flac", filename="a2.flac", title="A2",
                    artist="Artist One", album_artist="Artist One", album="Album A",
                    genre="Rock", year=1990, bitrate=800000, duration=220,
                    file_size=2000, created_at=old, availability_status="available",
                ),
                Song(
                    path="/music/b.mp3", filename="b.mp3", title="B",
                    artist="Artist Two", album="Album B", genre="Pop", year=2024,
                    bitrate=320000, duration=180, file_size=3000, created_at=now,
                    availability_status="available",
                ),
                Song(
                    path="/music/c.mp3", filename="c.mp3", title="C",
                    artist="Artist Three", album="Album C", genre="Pop", year=2010,
                    bitrate=128000, duration=100, file_size=4000, created_at=now,
                    availability_status="available",
                ),
                Song(
                    path="/music/missing.mp3", filename="missing.mp3", title="Missing",
                    artist="Ignored", album="Ignored", genre="Jazz", year=2026,
                    bitrate=9999999, duration=9999, file_size=999999,
                    created_at=now, availability_status="missing",
                ),
            ]
        )
        db.commit()

        analytics = library_analytics.calculate(db)

        assert analytics["songs"] == 4
        assert analytics["albums"] == 3
        assert analytics["artists"] == 3
        assert analytics["genres"] == 2
        assert analytics["storage_bytes"] == 10000
        assert analytics["average_bitrate"] == 562000
        assert analytics["average_duration"] == 175
        assert analytics["recently_added"] == 2
        assert analytics["largest_album"] == {
            "name": "Album A",
            "artist": "Artist One",
            "song_count": 2,
            "storage_bytes": 3000,
            "year": 1990,
        }
        assert analytics["newest_album"]["name"] == "Album B"
        assert analytics["oldest_album"]["name"] == "Album A"


def test_empty_library_analytics_are_stable():
    with _session() as db:
        analytics = library_analytics.calculate(db)

        assert analytics["songs"] == 0
        assert analytics["storage_bytes"] == 0
        assert analytics["average_bitrate"] == 0
        assert analytics["average_duration"] == 0
        assert analytics["largest_album"] is None
        assert analytics["newest_album"] is None
        assert analytics["oldest_album"] is None
