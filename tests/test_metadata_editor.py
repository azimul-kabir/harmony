import io
import json

import pytest

from app.services import metadata_editor


class _Response(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *_args): return False


def test_musicbrainz_search_uses_manually_supplied_terms(monkeypatch):
    captured = {}
    payload = {"recordings": [{"id": "recording-id", "title": "Karar Oi Louho Kopat", "score": 100,
        "artist-credit": [{"name": "Artcell"}], "releases": [{"id": "12345678-1234-1234-1234-123456789abc",
        "title": "Riotous 14", "date": "2024-01-01", "media": [{"position": 1, "track": [{"number": "3"}]}]}]}]}

    def fake_open(request, timeout):
        captured["url"] = request.full_url
        return _Response(json.dumps(payload).encode())

    monkeypatch.setattr(metadata_editor, "urlopen", fake_open)
    results = metadata_editor.search_musicbrainz(title="Karar Oi Louho Kopat", artist="Artcell", album="Riotous 14")
    assert "G%20Series" not in captured["url"]
    assert "Artcell" in captured["url"]
    assert results[0]["album"] == "Riotous 14"
    assert results[0]["track"] == "3"
    assert results[0]["artwork_url"].endswith("/front-250")


def test_musicbrainz_search_requires_a_term():
    with pytest.raises(ValueError, match="Enter a title"):
        metadata_editor.search_musicbrainz(title=" ", artist=None, album=None)


def test_write_metadata_preserves_unrelated_tags(monkeypatch, tmp_path):
    class FakeAudio:
        def __init__(self):
            self.tags = {"title": ["Bad title"], "isrc": ["KEEP-ME"]}
            self.saved = False
        def __setitem__(self, key, value): self.tags[key] = value
        def save(self): self.saved = True

    audio = FakeAudio()
    monkeypatch.setattr(metadata_editor, "File", lambda *_args, **_kwargs: audio)
    metadata_editor.write_metadata(tmp_path / "song.mp3", {"title": "Correct title", "artist": "Correct artist",
        "album": None, "album_artist": None, "genre": None, "year": 2024, "track": 3, "disc": 1})
    assert audio.tags["title"] == ["Correct title"]
    assert audio.tags["isrc"] == ["KEEP-ME"]
    assert audio.saved is True
