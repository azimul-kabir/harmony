from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.library import _serialize_song, list_songs
from app.api.schemas.library import SongResponse
from app.database.base import Base
from app.database.models import Song


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_song_response_marks_recently_added_tracks():
    song = Song(
        path="/music/recent.mp3",
        filename="recent.mp3",
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )

    assert _serialize_song(song)["recently_added"] is True


def test_song_response_does_not_expose_legacy_lyrics_columns():
    song = Song(
        path="/music/legacy-lyrics.mp3",
        filename="legacy-lyrics.mp3",
        lyrics="Legacy text",
        lyrics_source="embedded",
        lyrics_synced=False,
    )

    response = _serialize_song(song)

    assert "has_lyrics" not in response
    assert "lyrics_source" not in response
    assert "lyrics_synced" not in response


def test_song_response_falls_back_when_a_legacy_song_has_no_created_at():
    indexed_at = datetime.now(UTC).replace(tzinfo=None)
    song = Song(
        path="/music/legacy.mp3",
        filename="legacy.mp3",
        created_at=None,
        last_indexed_at=indexed_at,
    )

    response = _serialize_song(song)

    assert response["date_added"] == indexed_at
    assert response["recently_added"] is True


def test_library_song_payload_repairs_nullable_legacy_status_fields():
    """A legacy NULL must not invalidate the full /songs response page."""
    with _session() as db:
        song = Song(
            path="/music/legacy-nullable.mp3",
            filename="legacy-nullable.mp3",
            availability_status="available",
            artwork_status=None,
            download_source=None,
        )
        db.add(song)
        db.commit()

        payload = list_songs(
            db=db,
            playlist_id=None,
            year=None,
            min_bitrate=None,
            max_bitrate=None,
            limit=None,
            offset=0,
        )

        assert payload[0]["artwork_status"] == "missing"
        assert payload[0]["download_source"] == "filesystem"
        SongResponse.model_validate(payload[0])
