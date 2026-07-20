from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.library import search_library
from app.database.base import Base
from app.database.models import Playlist, PlaylistTrack, Song
from app.services.library_search import SearchFilters, library_search


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed(db: Session) -> tuple[Song, Song]:
    first = Song(
        path="/music/aurora.flac",
        filename="01 aurora-master.flac",
        title="Northern Lights",
        artist="Aurora Lane",
        album="Midnight Atlas",
        genre="Dream Pop",
        spotify_track_id="spotify-alpha-123",
        musicbrainz_recording_id="mbid-alpha-456",
        isrc="USAAA2600001",
        bitrate=320000,
        year=2026,
        availability_status="available",
    )
    second = Song(
        path="/music/hidden.mp3",
        filename="hidden-demo.mp3",
        title="Hidden Demo",
        artist="Archive Artist",
        album="Lost Files",
        genre="Rock",
        spotify_track_id="spotify-hidden",
        availability_status="missing",
    )
    playlist = Playlist(spotify_id="playlist-1", name="Night Drive")
    db.add_all([first, second, playlist])
    db.flush()
    db.add(
        PlaylistTrack(
            playlist_id=playlist.id,
            spotify_track_id=first.spotify_track_id,
            position=1,
        )
    )
    db.flush()
    library_search.index_song(db, first.id)
    library_search.index_song(db, second.id)
    db.commit()
    return first, second


def test_search_covers_every_indexed_field():
    with _session() as db:
        first, _ = _seed(db)

        queries = [
            "Northern",
            "Aurora",
            "Midnight",
            "Dream",
            "Night Drive",
            "aurora master",
            "spotify alpha",
            "mbid alpha",
            "USAAA2600001",
        ]
        for query in queries:
            page = library_search.search(db, query)
            assert page.song_ids == [first.id], query


def test_search_is_incremental_and_excludes_missing_by_default():
    with _session() as db:
        first, second = _seed(db)

        assert library_search.search(db, "Hidden").song_ids == []
        assert library_search.search(
            db,
            "Hidden",
            filters=SearchFilters(include_missing=True),
        ).song_ids == [second.id]

        first.title = "Polar Sky"
        library_search.index_song(db, first.id)
        db.commit()

        assert library_search.search(db, "Northern").song_ids == []
        assert library_search.search(db, "Polar").song_ids == [first.id]


def test_search_api_supports_structured_filters():
    with _session() as db:
        first, _ = _seed(db)
        response = search_library(
            q="Aurora",
            db=db,
            artist="Aurora Lane",
            album="Midnight Atlas",
            genre="Dream Pop",
            playlist_id=1,
            year=2026,
            min_bitrate=300000,
            max_bitrate=400000,
            include_missing=False,
            limit=20,
            offset=0,
        )

        assert response["total"] == 1
        assert response["items"][0]["id"] == first.id
        assert response["items"][0]["playlist_sources"][0]["name"] == "Night Drive"
