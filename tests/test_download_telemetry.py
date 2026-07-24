import time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database.base import Base
from app.database.models import DownloadJob
from app.services import download_telemetry
from app.services.download_telemetry import heartbeat_ticker, update_telemetry


def test_update_telemetry_persists_bounded_provider_neutral_values():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        job = DownloadJob(
            spotify_url="source",
            title="Song",
            artist="Artist",
            status="running",
        )
        db.add(job)
        db.commit()
        update_telemetry(
            db,
            job,
            stage="downloading",
            progress_percent=140,
            worker_name="worker-one",
            bytes_downloaded=1024,
            bytes_total=4096,
            transfer_rate_bps=512,
            eta_seconds=6,
        )
        db.refresh(job)
        assert job.pipeline_stage == "downloading"
        assert job.progress_percent == 100
        assert job.worker_name == "worker-one"
        assert job.heartbeat_at is not None
        assert job.bytes_downloaded == 1024
        assert job.bytes_total == 4096
        assert job.transfer_rate_bps == 512
        assert job.eta_seconds == 6


def test_heartbeat_ticker_updates_through_an_independent_session(
    tmp_path, monkeypatch
):
    engine = create_engine(f"sqlite:///{tmp_path / 'heartbeat.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(download_telemetry, "SessionLocal", sessions)
    monkeypatch.setattr(download_telemetry, "HEARTBEAT_INTERVAL_SECONDS", 0.01)
    with Session(engine) as db:
        job = DownloadJob(
            spotify_url="source",
            title="Song",
            artist="Artist",
            status="running",
        )
        db.add(job)
        db.commit()
        with heartbeat_ticker(job.id):
            time.sleep(0.04)
        db.expire_all()
        assert db.get(DownloadJob, job.id).heartbeat_at is not None
