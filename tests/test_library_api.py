from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.library import _serialize_song, list_collections, list_songs
from app.api.schemas.library import SongResponse
from app.database.base import Base
from app.database.models import Song


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_collections_are_generated_from_available_library_songs():
    with _session() as db:
        db.add_all(
            [
                Song(
                    path="/music/recent.mp3",
                    filename="recent.mp3",
                    title="Recent",
                    artist="Artist",
                    album="Album",
                    bitrate=320000,
                    artwork_status="missing",
                    availability_status="available",
                    created_at=datetime.now(UTC).replace(tzinfo=None),
                ),
                Song(
                    path="/music/old.mp3",
                    filename="old.mp3",
                    title="Old",
                    artist="Artist",
                    album="Album",
                    bitrate=128000,
                    artwork_status="embedded",
                    availability_status="available",
                    created_at=(datetime.now(UTC) - timedelta(days=30)).replace(
                        tzinfo=None
                    ),
                ),
                Song(
                    path="/music/missing.mp3",
                    filename="missing.mp3",
                    artwork_status="missing",
                    availability_status="missing",
                ),
            ]
        )
        db.commit()

        collections = {item["id"]: item for item in list_collections(db)}

        assert collections["recently-added"]["song_count"] == 1
        assert collections["highest-bitrate"]["song_count"] == 1
        assert collections["missing-artwork"]["song_count"] == 1
        assert collections["missing-metadata"]["song_count"] == 0
        assert collections["recently-downloaded"]["song_count"] == 0
        assert collections["recently-modified"]["song_count"] == 0
        assert collections["large-albums"]["song_count"] == 0
        assert collections["favorites"]["song_count"] == 0


def test_song_response_marks_recently_added_tracks():
    song = Song(
        path="/music/recent.mp3",
        filename="recent.mp3",
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )

    assert _serialize_song(song)["recently_added"] is True


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
