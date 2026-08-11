import os
from datetime import timedelta

import pytest

from app.core.config import get_settings
from app.database.models import DownloadJob
from app.database.session import SessionLocal
from app.services.download_telemetry import utcnow_naive
from app.services.settings_service import (
    configured_download_workers,
    initialize_defaults,
    update_settings,
)
from app.services.staging_cleanup import cleanup_staging_downloads


def test_saved_worker_count_controls_runtime_and_is_bounded():
    with SessionLocal() as db:
        initialize_defaults(db)
        original = get_settings().max_parallel_downloads
        try:
            assert configured_download_workers(db) == 2
            update_settings(db, "downloads", {"download_workers": 5})
            assert configured_download_workers(db) == 5
            assert get_settings().max_parallel_downloads == 5
            with pytest.raises(ValueError, match="between 1 and 8"):
                update_settings(db, "downloads", {"download_workers": 9})
        finally:
            get_settings().max_parallel_downloads = original


def test_staging_cleanup_preserves_resumable_and_fresh_files(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    active = staging / "active.mp3"
    recent_failure = staging / "recent-failure.mp3"
    expired = staging / "expired.mp3"
    fresh = staging / "fresh.mp3"
    for path in (active, recent_failure, expired, fresh):
        path.write_bytes(b"audio")
    old_timestamp = (utcnow_naive() - timedelta(days=10)).timestamp()
    for path in (active, recent_failure, expired):
        os.utime(path, (old_timestamp, old_timestamp))

    with SessionLocal() as db:
        db.add_all(
            (
                DownloadJob(
                    spotify_url="spotify:track:active",
                    title="Active",
                    artist="Artist",
                    status="queued",
                    output_file=str(active),
                    updated_at=utcnow_naive() - timedelta(days=10),
                ),
                DownloadJob(
                    spotify_url="spotify:track:recent-failure",
                    title="Recent failure",
                    artist="Artist",
                    status="failed",
                    output_file=str(recent_failure),
                    updated_at=utcnow_naive(),
                ),
            )
        )
        db.commit()

        assert cleanup_staging_downloads(db, staging) == 1

    assert active.exists()
    assert recent_failure.exists()
    assert fresh.exists()
    assert not expired.exists()
