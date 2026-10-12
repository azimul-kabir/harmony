import io
import json
import sqlite3
import zipfile
from datetime import timedelta

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.time import utcnow_naive
from app.database.models import AppSetting, ScheduleRun, SyncSource
from app.database.session import SessionLocal
from app.main import app
from app.services import operations
from app.services.operations import create_backup, restore_backup


def test_settings_export_and_import_round_trip():
    client = TestClient(app)
    client.get("/settings")
    exported = client.get("/api/settings/operations/settings-export")
    assert exported.status_code == 200
    payload = exported.json()
    assert payload["format"] == "harmony-settings"
    assert all(item["key"] != "navidrome_password" for item in payload["settings"])

    timezone = next(item for item in payload["settings"] if item["key"] == "timezone")
    timezone["value"] = "UTC"
    imported = client.post(
        "/api/settings/operations/settings-import",
        files={"file": ("settings.json", json.dumps(payload), "application/json")},
    )
    assert imported.status_code == 200
    assert client.get("/api/settings/general").json()["timezone"] == "UTC"


def test_backup_contains_manifest_database_and_artwork(monkeypatch, tmp_path):
    runtime = get_settings()
    artwork = tmp_path / "artwork"
    artwork.mkdir()
    (artwork / "cover.jpg").write_bytes(b"cover")
    monkeypatch.setattr(runtime, "artwork_cache_path", str(artwork))

    archive, _ = create_backup()
    try:
        with zipfile.ZipFile(archive) as bundle:
            assert {"manifest.json", "database/harmony.db", "artwork/cover.jpg"} <= set(bundle.namelist())
            assert json.loads(bundle.read("manifest.json"))["format"] == "harmony-backup"
    finally:
        archive.unlink()
        archive.parent.rmdir()


def test_restore_replaces_database_with_validated_snapshot(monkeypatch, tmp_path):
    runtime = get_settings()
    artwork = tmp_path / "restore-artwork"
    monkeypatch.setattr(runtime, "artwork_cache_path", str(artwork))
    with SessionLocal() as db:
        db.add(AppSetting(key="restore_marker", value="before", type="string", category="general"))
        db.commit()
    archive, _ = create_backup()
    backup_data = archive.read_bytes()
    archive.unlink()
    archive.parent.rmdir()

    with SessionLocal() as db:
        db.get(AppSetting, "restore_marker").value = "after"
        db.commit()
    result = restore_backup(backup_data)

    with SessionLocal() as db:
        assert db.get(AppSetting, "restore_marker").value == "before"
    assert result["restart_recommended"] is True


def test_schedule_history_marks_late_scheduled_runs():
    with SessionLocal() as db:
        source = SyncSource(
            type="playlist", spotify_id="history", spotify_url="https://open.spotify.com/playlist/history",
            name="History", enabled=True,
        )
        db.add(source)
        db.commit()
        db.refresh(source)
        started = utcnow_naive()
        db.add(ScheduleRun(
            source_id=source.id, trigger="scheduled", status="failed",
            scheduled_for=started - timedelta(minutes=8), started_at=started,
            completed_at=started, delay_seconds=480, message="Provider unavailable",
        ))
        db.commit()
        source_id = source.id

    response = TestClient(app).get(f"/api/sources/{source_id}/schedule-history")
    assert response.status_code == 200
    assert response.json()[0]["missed"] is True
    assert response.json()[0]["delay_seconds"] == 480


def _backup_bytes() -> bytes:
    archive, _ = create_backup()
    try:
        return archive.read_bytes()
    finally:
        archive.unlink()
        archive.parent.rmdir()


def _archive_with_database(database: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("manifest.json", json.dumps({"format": "harmony-backup", "version": 1}))
        bundle.writestr("database/harmony.db", database)
    return buffer.getvalue()


def test_backup_stores_artwork_without_recompressing(monkeypatch, tmp_path):
    artwork = tmp_path / "artwork"
    artwork.mkdir()
    (artwork / "cover.jpg").write_bytes(b"cover" * 100)
    monkeypatch.setattr(get_settings(), "artwork_cache_path", str(artwork))

    archive, _ = create_backup()
    try:
        with zipfile.ZipFile(archive) as bundle:
            assert bundle.getinfo("artwork/cover.jpg").compress_type == zipfile.ZIP_STORED
            assert bundle.getinfo("database/harmony.db").compress_type == zipfile.ZIP_DEFLATED
    finally:
        archive.unlink()
        archive.parent.rmdir()


def test_restore_endpoint_restores_uploaded_archive(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "artwork_cache_path", str(tmp_path / "artwork"))
    with SessionLocal() as db:
        db.add(AppSetting(key="restore_marker", value="before", type="string", category="general"))
        db.commit()
    backup = _backup_bytes()
    with SessionLocal() as db:
        db.get(AppSetting, "restore_marker").value = "after"
        db.commit()

    response = TestClient(app).post(
        "/api/settings/operations/restore",
        files={"file": ("backup.zip", backup, "application/zip")},
    )

    assert response.status_code == 200
    assert response.json()["restart_recommended"] is True
    with SessionLocal() as db:
        assert db.get(AppSetting, "restore_marker").value == "before"


def test_restore_rejects_damaged_or_foreign_databases(tmp_path):
    foreign = tmp_path / "foreign.db"
    connection = sqlite3.connect(foreign)
    connection.execute("CREATE TABLE notes (body TEXT)")
    connection.commit()
    connection.close()
    client = TestClient(app)

    for database, message in [
        (b"not a database" * 100, "damaged or is not a SQLite database"),
        (foreign.read_bytes(), "not a Harmony database"),
    ]:
        response = client.post(
            "/api/settings/operations/restore",
            files={"file": ("backup.zip", _archive_with_database(database), "application/zip")},
        )
        assert response.status_code == 422
        assert message in response.json()["detail"]


def test_backup_and_restore_refuse_to_overlap():
    client = TestClient(app)
    assert operations._operation_lock.acquire(blocking=False)
    try:
        assert client.get("/api/settings/operations/backup").status_code == 409
        restored = client.post(
            "/api/settings/operations/restore",
            files={"file": ("backup.zip", b"PK", "application/zip")},
        )
        assert restored.status_code == 409
        assert "already running" in restored.json()["detail"]
    finally:
        operations._operation_lock.release()
