from __future__ import annotations

import io
import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.database.models import AppSetting
from app.database.session import SessionLocal, engine
from app.services.settings_service import RETIRED_SETTING_KEYS, apply_runtime_overrides

BACKUP_VERSION = 1


def _database_path() -> Path:
    url = get_settings().database_url
    if not url.startswith("sqlite:///") or url.endswith(":memory:"):
        raise ValueError("Backup and restore currently require a file-backed SQLite database.")
    return Path(url.removeprefix("sqlite:///"))


def export_settings(db) -> dict:
    rows = db.scalars(
        select(AppSetting)
        .where(AppSetting.key.not_in(RETIRED_SETTING_KEYS))
        .order_by(AppSetting.key)
    ).all()
    return {
        "format": "harmony-settings",
        "version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "settings": [
            {"key": row.key, "value": row.value, "type": row.type, "category": row.category}
            for row in rows
        ],
    }


def import_settings(db, payload: dict) -> int:
    if payload.get("format") != "harmony-settings" or payload.get("version") != 1:
        raise ValueError("This is not a supported Harmony settings export.")
    items = payload.get("settings")
    if not isinstance(items, list):
        raise ValueError("The settings export is missing its settings list.")
    changed = 0
    for item in items:
        if not isinstance(item, dict) or not {"key", "value", "type", "category"} <= item.keys():
            raise ValueError("The settings export contains an invalid entry.")
        key = str(item["key"])
        if key in RETIRED_SETTING_KEYS:
            continue
        row = db.get(AppSetting, key)
        if row is None:
            row = AppSetting(key=key, value=str(item["value"]), type=str(item["type"]), category=str(item["category"]))
            db.add(row)
        else:
            row.value, row.type, row.category = str(item["value"]), str(item["type"]), str(item["category"])
        changed += 1
    db.commit()
    apply_runtime_overrides(db)
    return changed


def create_backup() -> tuple[Path, str]:
    database = _database_path()
    if not database.exists():
        raise ValueError("The Harmony database does not exist.")
    temp_dir = Path(tempfile.mkdtemp(prefix="harmony-backup-"))
    snapshot = temp_dir / "harmony.db"
    archive = temp_dir / f"harmony-backup-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.zip"
    source = sqlite3.connect(database)
    target = sqlite3.connect(snapshot)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    manifest = {"format": "harmony-backup", "version": BACKUP_VERSION, "created_at": datetime.now(UTC).isoformat()}
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest, indent=2))
        bundle.write(snapshot, "database/harmony.db")
        artwork = Path(get_settings().artwork_cache_path)
        if artwork.is_dir():
            for path in artwork.rglob("*"):
                if path.is_file():
                    bundle.write(path, Path("artwork") / path.relative_to(artwork))
    snapshot.unlink(missing_ok=True)
    return archive, archive.name


def restore_backup(data: bytes) -> dict:
    database = _database_path()
    with tempfile.TemporaryDirectory(prefix="harmony-restore-") as raw_dir:
        temp_dir = Path(raw_dir)
        try:
            bundle = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise ValueError("The uploaded file is not a valid ZIP backup.") from exc
        with bundle:
            names = set(bundle.namelist())
            if "manifest.json" not in names or "database/harmony.db" not in names:
                raise ValueError("The archive is missing its manifest or database snapshot.")
            manifest = json.loads(bundle.read("manifest.json"))
            if manifest.get("format") != "harmony-backup" or manifest.get("version") != BACKUP_VERSION:
                raise ValueError("This backup format is not supported.")
            snapshot = temp_dir / "restore.db"
            snapshot.write_bytes(bundle.read("database/harmony.db"))
            check = sqlite3.connect(snapshot)
            try:
                if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("The backup database failed its integrity check.")
            finally:
                check.close()
            engine.dispose()
            source = sqlite3.connect(snapshot)
            target = sqlite3.connect(database)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
            artwork_root = Path(get_settings().artwork_cache_path)
            artwork_root.mkdir(parents=True, exist_ok=True)
            restored_artwork = 0
            for name in names:
                path = Path(name)
                if not name.startswith("artwork/") or name.endswith("/") or ".." in path.parts:
                    continue
                destination = artwork_root.joinpath(*path.parts[1:])
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(name) as source_file, destination.open("wb") as target_file:
                    shutil.copyfileobj(source_file, target_file)
                restored_artwork += 1
    with SessionLocal() as db:
        apply_runtime_overrides(db)
    return {"status": "restored", "artwork_files": restored_artwork, "restart_recommended": True}
