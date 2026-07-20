from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database.base import Base
from app.database.models import Song
from app.services.collections import collection_engine


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_initial_smart_collections_are_live_index_queries():
    now = datetime.now(UTC).replace(tzinfo=None)
    old = now - timedelta(days=30)
    with _session() as db:
        for track in range(1, 11):
            db.add(
                Song(
                    path=f"/music/large/{track}.flac",
                    filename=f"{track}.flac",
                    title=f"Large Track {track}",
                    artist="Big Artist",
                    album_artist="Big Artist",
                    album="Large Album",
                    track=track,
                    bitrate=1000000 if track == 1 else 800000,
                    artwork_status="embedded",
                    download_source="filesystem",
                    created_at=old,
                    last_modified=old,
                    availability_status="available",
                )
            )
        db.add_all(
            [
                Song(
                    path="/music/recent.mp3",
                    filename="recent.mp3",
                    title="Recent Download",
                    artist="New Artist",
                    album="New Album",
                    bitrate=320000,
                    artwork_status="missing",
                    download_source="youtube-music",
                    created_at=now,
                    last_modified=now,
                    availability_status="available",
                ),
                Song(
                    path="/music/incomplete.mp3",
                    filename="incomplete.mp3",
                    title=None,
                    artist="Unknown",
                    album=None,
                    bitrate=128000,
                    artwork_status="embedded",
                    download_source="filesystem",
                    created_at=old,
                    last_modified=old,
                    availability_status="available",
                ),
            ]
        )
        db.commit()

        counts = {
            item["id"]: item["song_count"]
            for item in collection_engine.summaries(db)
        }

        assert counts == {
            "recently-added": 1,
            "recently-downloaded": 1,
            "highest-bitrate": 1,
            "missing-artwork": 1,
            "missing-metadata": 1,
            "recently-modified": 1,
            "large-albums": 10,
            "favorites": 0,
        }

        large_album_songs = db.scalars(
            collection_engine.statement("large-albums", sort_by="title")
        ).all()
        assert len(large_album_songs) == 10
        assert all(song.album == "Large Album" for song in large_album_songs)


def test_collection_definitions_expose_future_rule_shape():
    favorites = collection_engine.get("favorites")
    recently_downloaded = collection_engine.get("recently-downloaded")

    assert favorites is not None and favorites.placeholder is True
    assert favorites.rule.to_dict()["operator"] == "placeholder"
    assert recently_downloaded is not None
    assert recently_downloaded.rule.to_dict()["match"] == "all"
