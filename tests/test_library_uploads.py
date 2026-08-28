from pathlib import Path
import io
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database.models import Song
from app.database.session import SessionLocal
from app.services.library_uploads import (
    UploadValidationError,
    _auxiliary_action,
    analyze_metadata,
    create_batch,
    import_batch,
    load_batch,
    safe_upload_name,
    summarize_batch,
    set_batch_artwork,
    duplicate_preflight,
    cleanup_expired_batches,
    list_batches,
    save_upload,
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
    monkeypatch.setattr(uploads, "_require_free_space", lambda path, required_bytes: None)
    monkeypatch.setattr(uploads, "get_settings", lambda: type("Settings", (), {"music_path": str(tmp_path / "music")})())
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


def test_upload_storage_limits_and_recoverable_batch_listing(tmp_path, monkeypatch):
    import app.services.library_uploads as uploads

    settings = type("Settings", (), {
        "library_upload_max_active_batches": 1,
        "library_upload_expiration_hours": 2,
        "library_upload_min_free_bytes": 0,
        "library_upload_max_files": 10,
        "library_upload_max_batch_bytes": 3,
        "library_upload_max_file_bytes": 10,
    })()
    monkeypatch.setattr(uploads, "upload_root", lambda: tmp_path / "uploads")
    monkeypatch.setattr(uploads, "get_settings", lambda: settings)
    monkeypatch.setattr(uploads, "read_metadata", lambda path: {})

    batch = create_batch()
    assert batch["expires_at"] == batch["created_at"] + 7200
    with pytest.raises(UploadValidationError, match="Too many unfinished"):
        create_batch()
    with pytest.raises(UploadValidationError, match="total-size"):
        save_upload(batch["id"], "oversized.mp3", io.BytesIO(b"four"), max_bytes=10)
    assert list_batches()[0]["id"] == batch["id"]
    assert list_batches()[0]["total_bytes"] == 0


def test_expired_cleanup_preserves_active_batches(tmp_path, monkeypatch):
    import app.services.library_uploads as uploads

    monkeypatch.setattr(uploads, "upload_root", lambda: tmp_path / "uploads")
    expired = create_batch()
    protected = create_batch()
    for batch in (expired, protected):
        manifest = load_batch(batch["id"])
        manifest["created_at"] = int(time.time()) - 100
        uploads._write_manifest(uploads._batch_dir(batch["id"]), manifest)

    assert cleanup_expired_batches(max_age_seconds=10, protected_batch_ids={protected["id"]}) == 1
    with pytest.raises(UploadValidationError):
        load_batch(expired["id"])
    assert load_batch(protected["id"])["id"] == protected["id"]


def test_batch_summary_groups_albums_and_explains_inconsistencies():
    summary = summarize_batch({"items": [
        {"id": "one", "proposed": {"title": "One", "artist": "A", "album_artist": "A", "album": "Record", "genre": "Rock", "year": 2020, "track": 1}},
        {"id": "two", "proposed": {"title": "Two", "artist": "B", "album_artist": "Various Artists", "album": "Record", "genre": "Pop", "year": 2021, "track": 1}},
        {"id": "single", "proposed": {"title": "Loose", "artist": "Solo", "album_artist": "Solo", "album": None, "genre": None, "year": None, "track": None}},
    ]})

    assert summary["group_count"] == 2
    album = next(group for group in summary["groups"] if group["album"] == "Record")
    assert album["item_ids"] == ["one", "two"]
    assert album["values"]["album_artist"] is None
    assert album["findings"] == [
        "Album artist is inconsistent across this group.",
        "Year is inconsistent across this group.",
        "Genre is inconsistent across this group.",
        "Duplicate track numbers were detected.",
    ]


def test_staged_artwork_is_attached_to_server_derived_album_group(tmp_path, monkeypatch):
    import app.services.library_uploads as uploads
    monkeypatch.setattr(uploads, "upload_root", lambda: tmp_path / "uploads")
    batch = create_batch()
    manifest = load_batch(batch["id"])
    manifest["items"] = [{"id": "one", "proposed": {"title": "One", "artist": "A", "album_artist": "A", "album": "Record", "track": 1}}]
    uploads._write_manifest(uploads._batch_dir(batch["id"]), manifest)
    group_id = summarize_batch(manifest)["groups"][0]["id"]

    class Artwork:
        id = 42
        mime_type = "image/jpeg"

    group = set_batch_artwork(batch["id"], group_id, Artwork())
    assert group["artwork"] == {"id": 42, "mime_type": "image/jpeg", "url": "/api/artwork/42/file"}
    assert set_batch_artwork(batch["id"], group_id, None)["artwork"] is None


def test_duplicate_preflight_explains_exact_and_probable_library_matches():
    with SessionLocal() as db:
        exact = Song(path="/music/A/Record/01 - One.flac", filename="01 - One.flac", title="One", artist="A", album="Record", duration=180, isrc="USAAA0000001")
        probable = Song(path="/music/A/Other/Two.flac", filename="Two.flac", title="Two!", artist="Á", album="Other", duration=201)
        db.add_all([exact, probable]); db.commit()
        result = duplicate_preflight(db, {"items": [
            {"id": "exact", "destination": exact.path, "metadata": {"isrc": "USAAA0000001", "duration": 180}, "proposed": {"title": "One", "artist": "A", "album": "Record"}},
            {"id": "probable", "destination": "/music/A/New/Two.flac", "metadata": {"duration": 199}, "proposed": {"title": "two", "artist": "a", "album": "New"}},
        ]})

    by_id = {item["item_id"]: item for item in result["items"]}
    assert by_id["exact"]["recommended_action"] == "skip"
    assert by_id["exact"]["matches"][0]["tier"] == "exact"
    assert by_id["probable"]["recommended_action"] == "review"
    assert by_id["probable"]["matches"][0]["tier"] == "probable"


def test_confirmed_upload_creates_durable_locked_import_task(tmp_path, monkeypatch):
    import app.services.library_uploads as uploads
    from app.services.library_import_tasks import create_import_task
    monkeypatch.setattr(uploads, "upload_root", lambda: tmp_path / "uploads")
    batch = create_batch(); manifest = load_batch(batch["id"])
    manifest["items"] = [{"id": "one", "staged_name": "one.mp3", "proposed": {"title": "One"}}]
    uploads._write_manifest(uploads._batch_dir(batch["id"]), manifest)
    with SessionLocal() as db:
        task = create_import_task(db, batch_id=batch["id"], selections=[{"id": "one", "metadata": {"title": "One"}}], scan_navidrome=False)
        assert task.task_type == "library_import"
        assert task.resource_key == "library-files"
        assert task.resumable is True
        assert [item.original_path for item in task.bulk_items] == ["one"]


def test_import_worker_revalidates_and_skips_new_exact_duplicate(tmp_path, monkeypatch):
    import app.services.library_uploads as uploads
    import app.services.library_import_tasks as tasks
    from app.database.models import Task
    monkeypatch.setattr(uploads, "upload_root", lambda: tmp_path / "uploads")
    batch = create_batch(); manifest = load_batch(batch["id"])
    manifest["items"] = [{"id": "one", "staged_name": "one.mp3", "proposed": {"title": "One"}}]
    uploads._write_manifest(uploads._batch_dir(batch["id"]), manifest)
    with SessionLocal() as db:
        task = tasks.create_import_task(db, batch_id=batch["id"], selections=[{"id": "one", "metadata": {}}], scan_navidrome=False)
        task_id = task.id
        monkeypatch.setattr(tasks, "duplicate_preflight", lambda db, manifest: {"items": [{"item_id": "one", "matches": [{"tier": "exact"}]}]})
        tasks.LibraryImportWorker().process_task(db, task)
        refreshed = db.get(Task, task_id)
        assert refreshed.status == "completed_with_errors"
        assert refreshed.skipped_items == 1
        assert refreshed.item_failures[0].error_code == "DUPLICATE_CONFLICT"


def test_restart_requeues_running_resumable_import_item(tmp_path, monkeypatch):
    import app.services.library_uploads as uploads
    from app.services.library_import_tasks import create_import_task
    from app.services.task_service import recover_library_jobs
    monkeypatch.setattr(uploads, "upload_root", lambda: tmp_path / "uploads")
    batch = create_batch(); manifest = load_batch(batch["id"])
    manifest["items"] = [{"id": "one", "staged_name": "one.mp3", "proposed": {"title": "One"}}]
    uploads._write_manifest(uploads._batch_dir(batch["id"]), manifest)
    with SessionLocal() as db:
        task = create_import_task(db, batch_id=batch["id"], selections=[{"id": "one", "metadata": {}}], scan_navidrome=False)
        task.status = "running"; task.bulk_items[0].status = "running"; db.commit()
        recover_library_jobs(db); db.refresh(task); db.refresh(task.bulk_items[0])
        assert task.status == "queued"
        assert task.bulk_items[0].status == "queued"


def test_library_page_exposes_review_first_local_import():
    response = TestClient(app).get("/library")
    assert response.status_code == 200
    assert 'id="library-upload-open"' in response.text
    assert 'id="library-upload-dialog"' in response.text
    assert 'id="library-upload-discard"' in response.text
    assert "Request one Navidrome scan after import" in response.text
