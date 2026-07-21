from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.artwork import get_artwork, get_artwork_file, list_artwork
from app.database.base import Base
from app.database.models import Artwork
from app.services.artwork import ArtworkCandidate, ArtworkService


PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x02\x00\x00\x00\x03"
    b"\x08\x02\x00\x00\x00"
)


def _database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_cache_deduplicates_artwork_by_content(tmp_path):
    session_factory = _database()
    service = ArtworkService(tmp_path / "cache")

    with session_factory() as db:
        first = service.cache(db, ArtworkCandidate(PNG, "image/png", "embedded"))
        second = service.cache(db, ArtworkCandidate(PNG, "image/png", "folder"))
        db.commit()

        assert first.id == second.id
        assert db.query(Artwork).count() == 1
        assert Path(first.cache_path).read_bytes() == PNG
        assert (first.width, first.height) == (2, 3)


def test_folder_artwork_is_detected_and_cached(tmp_path, monkeypatch):
    session_factory = _database()
    service = ArtworkService(tmp_path / "cache")
    album = tmp_path / "album"
    album.mkdir()
    audio = album / "track.mp3"
    audio.write_bytes(b"audio")
    (album / "cover.png").write_bytes(PNG)
    monkeypatch.setattr(service, "_embedded_candidate", lambda path: None)

    with session_factory() as db:
        artwork = service.resolve_for_song(db, audio)
        db.commit()

        assert artwork is not None
        assert artwork.source == "folder"
        assert Path(artwork.cache_path).is_file()


def test_embedded_artwork_is_detected(tmp_path, monkeypatch):
    service = ArtworkService(tmp_path / "cache")
    picture = SimpleNamespace(data=PNG, mime="image/png", type=3)
    audio = SimpleNamespace(pictures=[picture], tags={})
    monkeypatch.setattr("app.services.artwork.File", lambda path, easy=False: audio)

    candidate = service._embedded_candidate(tmp_path / "track.flac")

    assert candidate is not None
    assert candidate.source == "embedded"
    assert candidate.mime_type == "image/png"
    assert candidate.data == PNG


def test_artwork_metadata_and_file_apis(tmp_path):
    session_factory = _database()
    service = ArtworkService(tmp_path / "cache")
    with session_factory() as db:
        artwork = service.cache(db, ArtworkCandidate(PNG, "image/png", "embedded"))
        db.commit()
        artwork_id = artwork.id

    with session_factory() as db:
        listing = list_artwork(db=db, limit=100, offset=0)
        metadata = get_artwork(artwork_id, db=db)
        image = get_artwork_file(artwork_id, db=db)

    assert listing["total"] == 1
    assert metadata["source"] == "embedded"
    assert metadata["url"] == f"/api/artwork/{artwork_id}/file"
    assert image.media_type == "image/png"
    assert Path(image.path).read_bytes() == PNG
