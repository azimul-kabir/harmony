from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.library_uploads import (
    UploadValidationError,
    _auxiliary_action,
    analyze_metadata,
    create_batch,
    import_batch,
    load_batch,
    safe_upload_name,
)


def test_safe_upload_name_removes_client_paths_and_rejects_non_audio():
    assert safe_upload_name(r"C:\downloads\Artist - Song.mp3") == "Artist - Song.mp3"
    assert safe_upload_name("../../Album/Song.FLAC") == "Song.FLAC"
    with pytest.raises(UploadValidationError, match="Unsupported audio type"):
        safe_upload_name("cover.jpg")


def test_analysis_proposes_conservative_branding_cleanup():
    result = analyze_metadata(
        {
            "title": "Northern Lights - www.bad-downloads.example",
            "artist": "The Artist",
            "album_artist": None,
            "album": "The Album [Downloaded from bad-downloads.example]",
            "genre": "Electronic",
            "year": 2025,
            "track": 2,
            "disc": 1,
        },
        original_name="02 - Northern Lights.mp3",
    )

    assert result["proposed"]["title"] == "Northern Lights"
    assert result["proposed"]["album"] == "The Album"
    assert result["proposed"]["album_artist"] == "The Artist"
    assert {change["field"] for change in result["changes"]} == {"title", "album"}


def test_analysis_preserves_legitimate_text_and_flags_missing_identity():
    result = analyze_metadata(
        {"title": "Visit", "artist": None, "album_artist": None, "album": None,
         "genre": None, "year": None, "track": None, "disc": None},
        original_name="Visit.mp3",
    )

    assert result["proposed"]["title"] == "Visit"
    assert len(result["warnings"]) == 2


def test_auxiliary_rules_remove_promotional_fields_and_only_branded_lyric_lines():
    assert _auxiliary_action("COMM:site", "Downloaded from https://bad.example")[0] == "remove"
    action, lyrics = _auxiliary_action(
        "USLT::eng",
        "First real line\nVisit www.bad.example\nSecond real line",
    )
    assert action == "rewrite"
    assert lyrics == "First real line\nSecond real line"
    assert _auxiliary_action("USLT::eng", "A real lyric about visiting home") == (None, None)


def test_partial_import_prunes_successes_and_keeps_failures_for_retry(tmp_path, monkeypatch):
    import app.services.library_uploads as uploads

    monkeypatch.setattr(uploads, "upload_root", lambda: tmp_path / "uploads")
    batch = create_batch()
    directory = uploads._batch_dir(batch["id"])
    first = directory / "first.mp3"
    second = directory / "second.mp3"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    manifest = load_batch(batch["id"])
    manifest["items"] = [
        {"id": "first", "staged_name": first.name, "proposed": {"title": "First"}},
        {"id": "second", "staged_name": second.name, "proposed": {"title": "Second"}},
    ]
    uploads._write_manifest(directory, manifest)
    monkeypatch.setattr(uploads, "sanitize_auxiliary_tags", lambda path, apply=False: [])
    monkeypatch.setattr(uploads, "write_metadata", lambda path, values: None)
    monkeypatch.setattr(uploads, "read_metadata", lambda path: {"title": path.stem})
    monkeypatch.setattr(
        uploads,
        "import_download",
        lambda db, path, download_source: Path("/music/First.mp3")
        if path.name == "first.mp3" else (_ for _ in ()).throw(OSError("disk error")),
    )

    class DB:
        def rollback(self):
            pass

    result = import_batch(DB(), batch["id"], [{"id": "first"}, {"id": "second"}])

    assert result["imported"] == 1
    assert result["items"][1]["error"] == "Harmony could not safely import this file."
    assert [item["id"] for item in load_batch(batch["id"])["items"]] == ["second"]


def test_library_page_exposes_review_first_local_import():
    response = TestClient(app).get("/library")
    assert response.status_code == 200
    assert 'id="library-upload-open"' in response.text
    assert 'id="library-upload-dialog"' in response.text
    assert "Request one Navidrome scan after import" in response.text
