from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.artwork import get_artwork, get_artwork_file, list_artwork
from app.database.base import Base
from app.database.models import Artwork, Song
from app.services.artwork import (
    ArtworkCandidate,
    ArtworkFetchSkipped,
    ArtworkService,
    resolve_musicbrainz_release_id,
)
from app.database.session import SessionLocal
from app.main import app


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


def test_manual_upload_reuses_content_and_association_removal_keeps_cache(tmp_path, monkeypatch):
    service = ArtworkService(tmp_path / "manual-cache")
    monkeypatch.setattr("app.api.artwork.ArtworkService", lambda: service)
    with SessionLocal() as db:
        first = Song(path="/music/art-one.mp3", filename="art-one.mp3")
        second = Song(path="/music/art-two.mp3", filename="art-two.mp3")
        db.add_all([first, second])
        db.commit()
        first_id, second_id = first.id, second.id
    client = TestClient(app)

    first_response = client.post(
        f"/api/artwork/songs/{first_id}",
        files={"file": ("cover.png", PNG, "image/png")},
    )
    second_response = client.post(
        f"/api/artwork/songs/{second_id}",
        files={"file": ("different-name.png", PNG, "image/png")},
    )

    assert first_response.status_code == second_response.status_code == 200
    artwork_id = first_response.json()["artwork"]["id"]
    assert second_response.json()["artwork"]["id"] == artwork_id
    assert first_response.json()["artwork"]["source"] == "manual"
    with SessionLocal() as db:
        assert db.get(Song, first_id).artwork_id == artwork_id
        assert db.get(Song, second_id).artwork_id == artwork_id
        artwork = db.get(Artwork, artwork_id)
        cache_path = Path(artwork.cache_path)
        assert cache_path.read_bytes() == PNG

    removed = client.delete(f"/api/artwork/songs/{first_id}")
    assert removed.status_code == 200
    with SessionLocal() as db:
        assert db.get(Song, first_id).artwork_id is None
        assert db.get(Song, first_id).artwork_status == "missing"
        assert db.get(Song, second_id).artwork_id == artwork_id
        assert db.get(Artwork, artwork_id) is not None
        assert cache_path.is_file()


def test_manual_upload_rejects_unsupported_content(tmp_path, monkeypatch):
    service = ArtworkService(tmp_path / "manual-cache")
    monkeypatch.setattr("app.api.artwork.ArtworkService", lambda: service)
    with SessionLocal() as db:
        song = Song(path="/music/not-image.mp3", filename="not-image.mp3")
        db.add(song)
        db.commit()
        song_id = song.id

    response = TestClient(app).post(
        f"/api/artwork/songs/{song_id}",
        files={"file": ("cover.jpg", b"this is not an image", "image/jpeg")},
    )

    assert response.status_code == 400
    assert "JPEG, PNG, or WebP" in response.json()["detail"]
    with SessionLocal() as db:
        assert db.get(Song, song_id).artwork_id is None


def test_fetches_and_caches_cover_art_archive_front_image(tmp_path, monkeypatch):
    session_factory = _database()
    service = ArtworkService(tmp_path / "cache")
    release_id = "24b78a62-5b88-4f3b-9bfc-1e1db47c50ad"
    monkeypatch.setattr(
        "app.services.artwork.get_settings",
        lambda: SimpleNamespace(
            cover_art_archive_base_url="https://coverartarchive.example",
            cover_art_archive_timeout_seconds=1,
            cover_art_archive_max_bytes=1024,
        ),
    )

    class Response:
        def read(self, amount):
            assert amount == 1025
            return PNG

        def geturl(self):
            return f"https://coverartarchive.example/release/{release_id}/front"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout):
        assert request.full_url == f"https://coverartarchive.example/release/{release_id}/front"
        assert timeout == 1
        return Response()

    monkeypatch.setattr("app.services.artwork.urlopen", fake_urlopen)

    with session_factory() as db:
        artwork = service.fetch_musicbrainz_release_artwork(db, release_id)
        db.commit()

        assert artwork.source == "remote"
        assert artwork.provider == "cover_art_archive"
        assert artwork.provider_id == release_id
        assert artwork.original_url == f"https://coverartarchive.example/release/{release_id}/front"
        assert Path(artwork.cache_path).read_bytes() == PNG


def test_cover_art_archive_rejects_non_image_response(tmp_path, monkeypatch):
    service = ArtworkService(tmp_path / "cache")
    monkeypatch.setattr(
        "app.services.artwork.get_settings",
        lambda: SimpleNamespace(
            cover_art_archive_base_url="https://coverartarchive.example",
            cover_art_archive_timeout_seconds=1,
            cover_art_archive_max_bytes=1024,
        ),
    )
    class Response:
        def read(self, _amount):
            return b"not an image"

        def geturl(self):
            return "https://coverartarchive.example/image"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr("app.services.artwork.urlopen", lambda *_args, **_kwargs: Response())
    with _database()() as db:
        try:
            service.fetch_musicbrainz_release_artwork(db, "24b78a62-5b88-4f3b-9bfc-1e1db47c50ad")
        except ValueError as error:
            assert str(error) == "Cover Art Archive returned an unsupported artwork format"
        else:
            raise AssertionError("expected non-image response to be rejected")


def _song(tmp_path, **values):
    return Song(path=str(tmp_path / "track.mp3"), filename="track.mp3", **values)


def test_resolver_uses_canonical_musicbrainz_album_id_for_observed_case(tmp_path):
    song = _song(
        tmp_path,
        musicbrainz_release_id="4f003785-1944-4b33-8a90-c676aab3db86",
        musicbrainz_release_group_id="c4f1b0ff-54e4-4ee3-a722-4c30892997b7",
    )

    result = resolve_musicbrainz_release_id(song)

    assert result.resolved
    assert result.release_id == "4f003785-1944-4b33-8a90-c676aab3db86"
    assert result.source_field == "songs.musicbrainz_release_id"
    assert not result.legacy_fallback_used


def test_release_group_is_never_used_as_cover_art_release_id(tmp_path):
    result = resolve_musicbrainz_release_id(
        _song(tmp_path, musicbrainz_release_group_id="c4f1b0ff-54e4-4ee3-a722-4c30892997b7")
    )

    assert result.release_id is None
    assert result.outcome == "release_group_only"


def test_invalid_release_id_is_rejected_before_provider_request(tmp_path, monkeypatch):
    service = ArtworkService(tmp_path / "cache")
    monkeypatch.setattr("app.services.artwork.urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network request")))
    with _database()() as db:
        song = _song(tmp_path, musicbrainz_release_id="not-a-uuid")
        try:
            service.fetch_for_song(db, song)
        except ArtworkFetchSkipped as error:
            assert error.resolution.outcome == "invalid_release_id"
        else:
            raise AssertionError("expected invalid identifier to be skipped")


def test_cached_artwork_avoids_remote_fetch_without_release_id(tmp_path, monkeypatch):
    service = ArtworkService(tmp_path / "cache")
    with _database()() as db:
        artwork = service.cache(db, ArtworkCandidate(PNG, "image/png", "remote"))
        song = _song(tmp_path)
        song.artwork = artwork
        monkeypatch.setattr(service, "fetch_musicbrainz_release_artwork", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network request")))

        resolved, outcome, cache_hit = service.fetch_for_song(db, song)

        assert resolved is artwork
        assert cache_hit
        assert outcome.outcome == "canonical_release_id_missing"


def test_forced_remote_refresh_requires_a_valid_release_id(tmp_path):
    service = ArtworkService(tmp_path / "cache")
    with _database()() as db:
        artwork = service.cache(db, ArtworkCandidate(PNG, "image/png", "remote"))
        song = _song(tmp_path)
        song.artwork = artwork
        try:
            service.fetch_for_song(db, song, force_remote=True)
        except ArtworkFetchSkipped as error:
            assert error.resolution.outcome == "canonical_release_id_missing"
        else:
            raise AssertionError("expected forced remote refresh to require an identifier")
