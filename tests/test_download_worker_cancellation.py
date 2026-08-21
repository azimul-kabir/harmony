from pathlib import Path

from app.database.crud import find_song_by_source
from app.database.models import DownloadJob, Song
from app.database.session import SessionLocal
from app.exceptions.library import DuplicateTrackError
from app.services.library_scanner import IndexResult
from app.workers import download_worker


def test_cancelled_during_download_removes_output_without_import(tmp_path, monkeypatch):
    db = SessionLocal()
    try:
        job = DownloadJob(spotify_url="https://example.test/track", source_url="https://example.test/track", title="Song", artist="Artist", status="running")
        db.add(job); db.commit(); db.refresh(job)
        output = tmp_path / "returned.mp3"; output.write_bytes(b"audio")
        imported = []
        def download(track, job_id):
            active = db.get(DownloadJob, job_id)
            active.status = "cancelled"; db.commit()
            return output
        monkeypatch.setattr(download_worker, "download_track", download)
        monkeypatch.setattr(download_worker, "write_genres", lambda *a, **k: imported.append("tags"))
        monkeypatch.setattr(download_worker, "import_downloaded_track", lambda **k: imported.append("import"))
        download_worker.process_job(db, job)
        db.refresh(job)
        assert job.status == "cancelled"
        assert not output.exists()
        assert imported == []
    finally:
        db.close()


def test_cancelled_before_import_after_genre_write_stops_transition(tmp_path, monkeypatch):
    db = SessionLocal()
    try:
        job = DownloadJob(spotify_url="https://example.test/track", source_url="https://example.test/track", title="Song", artist="Artist", status="running", genre="rock")
        db.add(job); db.commit(); db.refresh(job)
        output = tmp_path / "returned.mp3"; output.write_bytes(b"audio")
        calls = []
        monkeypatch.setattr(download_worker, "download_track", lambda track, job_id: output)
        def genre(*args, **kwargs):
            calls.append("genre")
            db.get(DownloadJob, job.id).status = "cancelled"; db.commit()
        monkeypatch.setattr(download_worker, "write_genres", genre)
        monkeypatch.setattr(download_worker, "import_downloaded_track", lambda **k: calls.append("import"))
        download_worker.process_job(db, job)
        db.refresh(job)
        assert calls == ["genre"] and job.status == "cancelled" and not output.exists()
    finally:
        db.close()


def test_pre_cancelled_job_never_calls_provider(monkeypatch):
    db = SessionLocal()
    try:
        job = DownloadJob(spotify_url="x", title="Song", artist="Artist", status="cancelled")
        db.add(job); db.commit()
        monkeypatch.setattr(download_worker, "download_track", lambda *args: (_ for _ in ()).throw(AssertionError("provider called")))
        download_worker.process_job(db, job)
        assert db.get(DownloadJob, job.id).status == "cancelled"
    finally:
        db.close()


def test_cancelled_after_import_does_not_complete(tmp_path, monkeypatch):
    db = SessionLocal()
    try:
        job = DownloadJob(spotify_url="x", title="Song", artist="Artist", status="running")
        db.add(job); db.commit(); db.refresh(job)
        output = tmp_path / "audio.mp3"; output.write_bytes(b"audio")
        monkeypatch.setattr(download_worker, "download_track", lambda *args: output)
        def imported(**kwargs):
            db.get(DownloadJob, job.id).status = "cancelled"; db.commit()
            return tmp_path / "library.mp3"
        monkeypatch.setattr(download_worker, "import_downloaded_track", imported)
        download_worker.process_job(db, job)
        assert db.get(DownloadJob, job.id).status == "cancelled"
    finally:
        db.close()


def test_late_exception_after_cancellation_does_not_fail_job(tmp_path, monkeypatch):
    db = SessionLocal()
    try:
        job = DownloadJob(spotify_url="x", title="Song", artist="Artist", status="running")
        db.add(job); db.commit(); db.refresh(job)
        output = tmp_path / "audio.mp3"; output.write_bytes(b"audio")
        monkeypatch.setattr(download_worker, "download_track", lambda *args: output)
        def explode(**kwargs):
            db.get(DownloadJob, job.id).status = "cancelled"; db.commit()
            raise RuntimeError("late worker failure sentinel")
        monkeypatch.setattr(download_worker, "import_downloaded_track", explode)
        download_worker.process_job(db, job)
        db.refresh(job)
        assert job.status == "cancelled" and "sentinel" not in (job.error or "")
    finally:
        db.close()


def test_import_retry_reuses_successfully_acquired_staging_file(tmp_path, monkeypatch):
    staging = tmp_path / "staging"
    staging.mkdir()
    output = staging / "audio.mp3"
    output.write_bytes(b"audio")
    library_file = tmp_path / "music" / "audio.mp3"
    calls = {"download": 0, "import": 0}

    db = SessionLocal()
    try:
        job = DownloadJob(
            spotify_url="spotify:track:resume",
            source_url="spotify:track:resume",
            title="Resume",
            artist="Artist",
            status="running",
            attempt_count=1,
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        monkeypatch.setattr(download_worker.get_settings(), "staging_path", str(staging))
        monkeypatch.setattr(download_worker, "write_genres", lambda *args, **kwargs: None)

        def download(*_args):
            calls["download"] += 1
            return output

        def import_track(**_kwargs):
            calls["import"] += 1
            if calls["import"] == 1:
                raise RuntimeError("temporary import failure")
            return library_file

        monkeypatch.setattr(download_worker, "download_track", download)
        monkeypatch.setattr(download_worker, "import_downloaded_track", import_track)
        monkeypatch.setattr(download_worker, "export_m3us_for_source_track", lambda *args: 0)

        download_worker.process_job(db, job)
        db.refresh(job)
        assert job.status == "queued"
        assert job.output_file == str(output.resolve())

        job.status = "running"
        job.attempt_count = 2
        job.next_attempt_at = None
        db.commit()
        download_worker.process_job(db, job)
        db.refresh(job)

        assert job.status == "completed"
        assert job.output_file == str(library_file)
        assert calls == {"download": 1, "import": 2}
    finally:
        db.close()


def test_cancelled_cleanup_failure_is_contained(tmp_path, monkeypatch):
    db = SessionLocal()
    try:
        job = DownloadJob(spotify_url="x", title="Song", artist="Artist", status="running")
        db.add(job); db.commit(); db.refresh(job)
        output = tmp_path / "audio.mp3"; output.write_bytes(b"audio")
        monkeypatch.setattr(download_worker, "download_track", lambda *args: (db.get(DownloadJob, job.id).__setattr__("status", "cancelled"), db.commit(), output)[2])
        monkeypatch.setattr(Path, "unlink", lambda self: (_ for _ in ()).throw(OSError("cleanup failure sentinel")))
        download_worker.process_job(db, job)
        assert db.get(DownloadJob, job.id).status == "cancelled"
    finally:
        db.close()


def test_late_duplicate_is_indexed_linked_and_exported(tmp_path, monkeypatch):
    db = SessionLocal()
    try:
        existing = tmp_path / "music" / "Cameo" / "Word Up" / "01 - Word Up.mp3"
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"existing")
        output = tmp_path / "download.mp3"
        output.write_bytes(b"download")
        song = Song(
            path=str(existing.resolve()),
            filename=existing.name,
            title="Word Up",
            artist="Cameo",
        )
        job = DownloadJob(
            spotify_url="https://open.spotify.com/track/single-version-id",
            source_url="https://open.spotify.com/track/single-version-id",
            source_provider="spotify",
            source_item_id="single-version-id",
            spotify_track_id="single-version-id",
            title="Word Up! - Single Version",
            artist="Cameo",
            status="running",
        )
        db.add_all([song, job])
        db.commit()
        db.refresh(job)

        monkeypatch.setattr(download_worker, "download_track", lambda *args: output)
        monkeypatch.setattr(
            download_worker,
            "import_downloaded_track",
            lambda **kwargs: (_ for _ in ()).throw(
                DuplicateTrackError("already exists", existing_path=existing)
            ),
        )
        monkeypatch.setattr(
            download_worker,
            "index_file",
            lambda *args, **kwargs: IndexResult(
                path=str(existing), status="unchanged", song_id=song.id
            ),
        )
        exported = []
        monkeypatch.setattr(
            download_worker,
            "export_m3us_for_source_track",
            lambda *args: exported.append(args[2:]) or 1,
        )

        download_worker.process_job(db, job)

        db.refresh(job)
        assert job.status == "skipped"
        assert job.reason_code == "duplicate_in_library"
        assert not output.exists()
        assert find_song_by_source(db, "spotify", "single-version-id").id == song.id
        assert exported == [("single-version-id", "single-version-id")]
    finally:
        db.close()


def test_no_match_for_available_library_song_is_skipped(monkeypatch, tmp_path):
    db = SessionLocal()
    try:
        library_file = tmp_path / "already-owned.mp3"
        library_file.write_bytes(b"audio")
        song = Song(
            path=str(library_file),
            filename=library_file.name,
            title="Already Owned",
            artist="Artist",
            isrc="OWNED123",
            availability_status="available",
        )
        job = DownloadJob(
            spotify_url="spotify:track:owned",
            source_url="spotify:track:owned",
            source_provider="spotify",
            source_item_id="owned",
            spotify_track_id="owned",
            title="Already Owned",
            artist="Artist",
            isrc="OWNED123",
            status="running",
        )
        db.add_all([song, job])
        db.commit()
        db.refresh(job)
        monkeypatch.setattr(
            download_worker,
            "download_track",
            lambda *args: (_ for _ in ()).throw(
                download_worker.DownloadFailed(
                    "exact_match_unavailable",
                    "Harmony could not obtain the requested track.",
                    "download",
                    retryable=False,
                )
            ),
        )

        download_worker.process_job(db, job)

        db.refresh(job)
        assert job.status == "skipped"
        assert job.reason_code == "duplicate_in_library"
        assert find_song_by_source(db, "spotify", "owned").id == song.id
    finally:
        db.close()
