from datetime import timedelta

from app.core.time import utcnow_naive
from app.database.models import SyncSource
from app.database.session import SessionLocal
from app.services.source_auto_sync import due_sources, next_sync_at


def _source(db, *, auto_sync=True, interval=60, attempted_minutes_ago=120):
    source = SyncSource(
        type="playlist",
        spotify_id=f"playlist-{attempted_minutes_ago}-{interval}",
        spotify_url="https://open.spotify.com/playlist/example",
        name="Scheduled playlist",
        enabled=True,
        auto_sync_enabled=auto_sync,
        auto_sync_interval_minutes=interval,
        auto_sync_last_attempt_at=utcnow_naive() - timedelta(minutes=attempted_minutes_ago),
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def test_due_sources_returns_enabled_schedule_after_interval():
    with SessionLocal() as db:
        source = _source(db)

        assert [item.id for item in due_sources(db)] == [source.id]


def test_due_sources_skips_disabled_auto_sync():
    with SessionLocal() as db:
        _source(db, auto_sync=False)

        assert due_sources(db) == []


def test_next_sync_enforces_fifteen_minute_minimum():
    with SessionLocal() as db:
        source = _source(db, interval=1, attempted_minutes_ago=1)

        assert next_sync_at(source) == source.auto_sync_last_attempt_at + timedelta(minutes=15)


def test_future_schedule_is_not_due():
    with SessionLocal() as db:
        _source(db, interval=360, attempted_minutes_ago=30)

        assert due_sources(db) == []
