from app.database.crud import UpsertStatus, find_song, upsert_song
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


def test_find_song_matches_spotify_track_id_before_text_fields():
    db = SessionLocal()

    db.query(Song).delete()
    db.commit()

    metadata = {
        "path": "/music/test-id.mp3",
        "filename": "test-id.mp3",
        "artist": "Tame Impala, JENNIE",
        "album_artist": "Tame Impala",
        "album": "Dracula (Remix)",
        "title": "Dracula - JENNIE Remix",
        "spotify_track_id": "5yvVYFDUpbnjcnRBgjwTzM",
        "spotify_album_id": "album-1",
        "isrc": "ISRC-ID",
        "track": 1,
        "disc": 1,
        "year": 2026,
        "genre": "Pop",
        "duration": 180,
        "file_size": 1000,
        "modified_time": 100,
    }

    _, song = upsert_song(db, metadata)

    match = find_song(
        db,
        title="Dracula - JENNIE Remix",
        artist="Tame Impala",
        spotify_track_id="5yvVYFDUpbnjcnRBgjwTzM",
    )

    assert match == song

    db.query(Song).delete()
    db.commit()


def test_find_song_matches_isrc_when_spotify_id_is_missing():
    db = SessionLocal()

    db.query(Song).delete()
    db.commit()

    metadata = {
        "path": "/music/test-isrc.mp3",
        "filename": "test-isrc.mp3",
        "artist": "Artist One, Artist Two",
        "album_artist": "Artist One",
        "album": "Album",
        "title": "Song",
        "spotify_track_id": None,
        "spotify_album_id": None,
        "isrc": "ISRC-ONLY",
        "track": 1,
        "disc": 1,
        "year": 2026,
        "genre": "Pop",
        "duration": 180,
        "file_size": 1000,
        "modified_time": 100,
    }

    _, song = upsert_song(db, metadata)

    match = find_song(
        db,
        title="Song",
        artist="Artist One",
        isrc="ISRC-ONLY",
    )

    assert match == song

    db.query(Song).delete()
    db.commit()
