from app.database.crud import UpsertStatus, upsert_song
from app.database.session import SessionLocal
from app.database.models import Song


def test_upsert_detects_updated_file():
    db = SessionLocal()

    # Clean table
    db.query(Song).delete()
    db.commit()

    metadata = {
        "path": "/music/test.mp3",
        "filename": "test.mp3",
        "artist": "Artist",
        "album_artist": "Artist",
        "album": "Album",
        "title": "Song",
        "track": 1,
        "disc": 1,
        "year": 2025,
        "genre": "Pop",
        "duration": 180,
        "file_size": 1000,
        "modified_time": 100,
    }

    # First insert
    status, _ = upsert_song(db, metadata)
    assert status == UpsertStatus.NEW

    # Simulate a changed file
    metadata["modified_time"] = 200

    status, _ = upsert_song(db, metadata)
    assert status == UpsertStatus.UPDATED

    db.query(Song).delete()
    db.commit()