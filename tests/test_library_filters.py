from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database.base import Base
from app.database.models import Song
from app.services.library_filters import (
    LibraryFilters,
    apply_song_filters,
    apply_song_sort,
)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_filters_compose_with_and_semantics():
    now = datetime.now(UTC).replace(tzinfo=None)
    with _session() as db:
        target = Song(
            path="/music/target.flac",
            filename="target.flac",
            title="Needs Album",
            artist="Filter Artist",
            album=None,
            genre="Electronic",
            codec="flac",
            bitrate=1000000,
            artwork_status="missing",
            created_at=now,
            availability_status="available",
        )
        db.add_all(
            [
                target,
                Song(
                    path="/music/wrong-codec.mp3",
                    filename="wrong-codec.mp3",
                    title="Complete",
                    artist="Filter Artist",
                    album="Album",
                    genre="Electronic",
                    codec="mp3",
                    bitrate=320000,
                    artwork_status="embedded",
                    created_at=now,
                    availability_status="available",
                ),
            ]
        )
        db.commit()

        statement = apply_song_filters(
            select(Song),
            LibraryFilters(
                artist="Filter Artist",
                genre="Electronic",
                codec="flac",
                min_bitrate=900000,
                downloaded_today=True,
                recently_added=True,
                missing_artwork=True,
                missing_metadata=True,
            ),
        )
        assert db.scalars(statement).all() == [target]


@pytest.mark.parametrize(
    ("sort_by", "expected_title"),
    [
        ("artist", "Alpha"),
        ("album", "Alpha"),
        ("title", "Alpha"),
        ("alphabetical", "Alpha"),
        ("recently_added", "Zulu"),
        ("recently_modified", "Zulu"),
        ("bitrate", "Zulu"),
        ("duration", "Zulu"),
        ("year", "Zulu"),
    ],
)
def test_all_supported_sorts(sort_by, expected_title):
    now = datetime.now(UTC).replace(tzinfo=None)
    with _session() as db:
        db.add_all(
            [
                Song(
                    path="/music/alpha.mp3",
                    filename="alpha.mp3",
                    title="Alpha",
                    artist="Alpha",
                    album="Alpha",
                    bitrate=128000,
                    duration=100,
                    year=2020,
                    created_at=now - timedelta(days=1),
                    last_modified=now - timedelta(days=1),
                ),
                Song(
                    path="/music/zulu.mp3",
                    filename="zulu.mp3",
                    title="Zulu",
                    artist="Zulu",
                    album="Zulu",
                    bitrate=320000,
                    duration=200,
                    year=2026,
                    created_at=now,
                    last_modified=now,
                ),
            ]
        )
        db.commit()
        statement = apply_song_sort(select(Song), sort_by)
        assert db.scalars(statement).first().title == expected_title
