from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database.models import MetadataHistory, MetadataSuggestion, Song, Task
from app.database.session import SessionLocal
from app.main import app
from app.services.metadata_intelligence import metadata_application_service


def _song(db):
    song = Song(
        path="/music/manual.mp3",
        filename="manual.mp3",
        title="Original title",
        artist="Original artist",
        album="Original album",
        track=2,
        track_total=10,
        availability_status="available",
    )
    db.add(song)
    db.commit()
    return song


def test_manual_preview_normalizes_values_and_rejects_invalid_fields():
    with SessionLocal() as db:
        song_id = _song(db).id
    client = TestClient(app)
    response = client.post(
        f"/api/library/songs/{song_id}/metadata/manual-preview",
        json={"changes": {"title": "  New   title  ", "isrc": "usabc1234567", "year": 99}},
    )
    assert response.status_code == 200
    operations = {item["field_name"]: item for item in response.json()["operations"]}
    assert operations["title"]["proposed_value"] == "New title"
    assert operations["isrc"]["proposed_value"] == "USABC1234567"
    assert operations["year"]["status"] == "invalid"

    unsupported = client.post(
        f"/api/library/songs/{song_id}/metadata/manual-preview",
        json={"changes": {"artwork_source": "upload"}},
    )
    assert unsupported.status_code == 400
    assert unsupported.json()["error"]["code"] == "manual_edit_invalid_field"


def test_manual_apply_is_queued_audited_and_reversible():
    with SessionLocal() as db:
        song_id = _song(db).id
    response = TestClient(app).post(
        f"/api/library/songs/{song_id}/metadata/manual-apply",
        json={
            "changes": {"title": "Edited title", "genre": "Ambient", "album": "Original album"},
            "initiated_by": "test-user",
        },
    )
    assert response.status_code == 200
    payload = response.json()

    with SessionLocal() as db:
        song = db.get(Song, song_id)
        assert song.title == "Original title"
        task = db.get(Task, payload["job_id"])
        suggestions = db.scalars(
            select(MetadataSuggestion).where(MetadataSuggestion.provider == "manual")
        ).all()
        assert {item.field_name for item in suggestions} == {"title", "genre"}
        metadata_application_service.process_task(db, task)
        db.refresh(song)
        history = db.scalars(
            select(MetadataHistory).where(MetadataHistory.entity_id == song_id)
        ).all()
        assert (song.title, song.genre) == ("Edited title", "Ambient")
        assert {item.change_source for item in history} == {"manual_edit"}
        assert all(item.audio_file_modified is False and item.reversible for item in history)

        title_history = next(item for item in history if item.field_name == "title")
        rollback = metadata_application_service.submit(
            db, [song_id], rollback_history_ids=[title_history.id]
        )
        metadata_application_service.process_task(db, db.get(Task, rollback["job_id"]))
        db.refresh(song)
        assert song.title == "Original title"


def test_manual_apply_rejects_the_entire_invalid_request():
    with SessionLocal() as db:
        song_id = _song(db).id
    response = TestClient(app).post(
        f"/api/library/songs/{song_id}/metadata/manual-apply",
        json={"changes": {"title": "Would be valid", "total_tracks": 1}},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "manual_edit_invalid_value"
    with SessionLocal() as db:
        assert db.scalars(select(MetadataSuggestion)).all() == []
