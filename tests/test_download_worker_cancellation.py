from pathlib import Path

from app.database.models import DownloadJob
from app.database.session import SessionLocal
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
        monkeypatch.setattr(download_worker, "enrich_tracks", lambda *a, **k: None)
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
        monkeypatch.setattr(download_worker, "enrich_tracks", lambda *args, **kwargs: None)
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
        monkeypatch.setattr(download_worker, "enrich_tracks", lambda *args, **kwargs: None)
        def explode(**kwargs):
            db.get(DownloadJob, job.id).status = "cancelled"; db.commit()
            raise RuntimeError("late worker failure sentinel")
        monkeypatch.setattr(download_worker, "import_downloaded_track", explode)
        download_worker.process_job(db, job)
        db.refresh(job)
        assert job.status == "cancelled" and "sentinel" not in (job.error or "")
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
