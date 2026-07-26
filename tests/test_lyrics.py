from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Song
from app.database.session import get_db
from app.main import app
from app.services.lyrics import MAX_LYRICS_BYTES, extract_lyrics


class ID3Tags(dict):
    def __init__(self, frames=None, **values):
        super().__init__(values)
        self.frames = frames or {}

    def getall(self, name):
        return self.frames.get(name, [])


def test_lrc_sidecar_takes_precedence_over_embedded_lyrics(tmp_path):
    audio = tmp_path / "song.mp3"
    audio.touch()
    audio.with_suffix(".lrc").write_text("[00:01.20]Sidecar line\n", encoding="utf-8")
    tags = ID3Tags({"USLT": [SimpleNamespace(text="Embedded line")]})

    lyrics = extract_lyrics(audio, tags)

    assert lyrics is not None
    assert lyrics.text == "[00:01.20]Sidecar line"
    assert lyrics.source == "sidecar_lrc"
    assert lyrics.synchronized is True


def test_embedded_id3_lyrics_supports_plain_and_synchronized_frames(tmp_path):
    audio = tmp_path / "song.mp3"
    audio.touch()

    plain = extract_lyrics(
        audio,
        ID3Tags({"USLT": [SimpleNamespace(text="First\r\nSecond")]}),
    )
    synced = extract_lyrics(
        audio,
        ID3Tags({"SYLT": [SimpleNamespace(text=[("First", 1230), ("Second", 61000)])]}),
    )

    assert plain is not None
    assert (plain.text, plain.source, plain.synchronized) == (
        "First\nSecond",
        "embedded",
        False,
    )
    assert synced is not None
    assert synced.text == "[00:01.23]First\n[01:01.00]Second"
    assert synced.synchronized is True


def test_oversized_sidecar_is_ignored(tmp_path):
    audio = tmp_path / "song.flac"
    audio.touch()
    audio.with_suffix(".txt").write_bytes(b"x" * (MAX_LYRICS_BYTES + 1))

    assert extract_lyrics(audio, {}) is None


def test_lyrics_endpoint_returns_text_without_putting_it_in_song_lists():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        song = Song(
            path="/music/song.mp3",
            filename="song.mp3",
            title="Song",
            artist="Artist",
            lyrics="[00:01.00]Hello",
            lyrics_source="sidecar_lrc",
            lyrics_synced=True,
        )
        db.add(song)
        db.commit()
        song_id = song.id

    def override_db():
        db = Session(engine)
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        item = client.get(f"/api/library/songs/{song_id}").json()
        response = client.get(f"/api/library/songs/{song_id}/lyrics")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert item["has_lyrics"] is True
    assert "lyrics" not in item
    assert response.status_code == 200
    assert response.json() == {
        "song_id": song_id,
        "title": "Song",
        "artist": "Artist",
        "lyrics": "[00:01.00]Hello",
        "source": "sidecar_lrc",
        "synchronized": True,
    }
