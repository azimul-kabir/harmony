from datetime import timedelta

from app.database.crud_downloads import claim_next_job
from app.database.models import AppSetting, DownloadJob
from app.database.session import SessionLocal
from app.domain.download_outcome import DownloadFailed
from app.services.download_telemetry import utcnow_naive
from app.workers import download_worker


def _job(**values):
    return DownloadJob(
        spotify_url=values.pop("spotify_url", "spotify:track:retry"),
        title="Retry me",
        artist="Artist",
        status="running",
        **values,
    )


def test_transient_failure_is_delayed_without_finishing_job():
    with SessionLocal() as db:
        job = _job(attempt_count=1)
        db.add(job)
        db.commit()

        scheduled = download_worker._schedule_retry(
            db,
            job,
            DownloadFailed(
                "provider_rate_limited",
                "The provider is rate limited.",
                "download",
                retryable=True,
            ),
        )

        assert scheduled is True
        assert job.status == "queued"
        assert job.pipeline_stage == "retry_wait"
        assert job.next_attempt_at > utcnow_naive()
        assert job.attempt_count == 1


def test_retry_stops_after_three_attempts_and_for_permanent_failures():
    with SessionLocal() as db:
        exhausted = _job(spotify_url="spotify:track:exhausted", attempt_count=3)
        permanent = _job(spotify_url="spotify:track:permanent", attempt_count=1)
        db.add_all((exhausted, permanent))
        db.commit()

        transient = DownloadFailed(
            "provider_error", "Provider error.", "download", retryable=True
        )
        mismatch = DownloadFailed(
            "exact_match_unavailable",
            "Exact match unavailable.",
            "validation",
            retryable=False,
        )

        assert download_worker._schedule_retry(db, exhausted, transient) is False
        assert download_worker._schedule_retry(db, permanent, mismatch) is False


def test_retry_setting_can_disable_automatic_recovery():
    with SessionLocal() as db:
        setting = AppSetting(
            key="retry_failed",
            value="false",
            type="boolean",
            category="downloads",
        )
        job = _job(attempt_count=1)
        db.add_all((setting, job))
        db.commit()

        assert download_worker._schedule_retry(
            db,
            job,
            DownloadFailed(
                "download_timeout", "Timed out.", "download", retryable=True
            ),
        ) is False


def test_claim_skips_delayed_retry_and_counts_provider_attempts():
    with SessionLocal() as db:
        delayed = DownloadJob(
            spotify_url="spotify:track:delayed",
            title="Delayed",
            artist="Artist",
            status="queued",
            next_attempt_at=utcnow_naive() + timedelta(minutes=5),
        )
        ready = DownloadJob(
            spotify_url="spotify:track:ready",
            title="Ready",
            artist="Artist",
            status="queued",
        )
        db.add_all((delayed, ready))
        db.commit()

        claimed = claim_next_job(db)

        assert claimed.id == ready.id
        assert claimed.attempt_count == 1
        assert delayed.status == "queued"
