from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database.models import MetadataHistory, MetadataSuggestion, Song
from app.database.session import SessionLocal
from app.main import app
from app.services.metadata_intelligence import MetadataServiceError, metadata_service, serialize_history


def add_song(db, *, title="Original"):
    song = Song(path=f"/music/{title}.mp3", filename=f"{title}.mp3", title=title,
                artist="Artist", album="Album", availability_status="available")
    db.add(song); db.commit(); db.refresh(song)
    return song


def create(db, song, value="Proposed", provider="test", **extra):
    item = metadata_service.create_suggestion(
        db, entity_type="song", entity_id=song.id, field_name="title",
        suggested_value=value, provider=provider, confidence=.9,
        confidence_level="high", positive_evidence={"isrc": "match"},
        conflicting_evidence=[], match_explanation="Strong title and artist match", **extra,
    )
    db.commit(); db.refresh(item)
    return item


def test_create_and_multiple_competing_suggestions():
    with SessionLocal() as db:
        song = add_song(db)
        first, second = create(db, song), create(db, song, "Alternative", "other")
        items, total = metadata_service.list_pending_suggestions(db, entity_type="song", entity_id=song.id)
        assert total == 2
        assert {item.id for item in items} == {first.id, second.id}
        assert first.current_value == '"Original"'


def test_accept_does_not_change_canonical_metadata_and_supersedes_old_acceptance():
    with SessionLocal() as db:
        song = add_song(db)
        first, second = create(db, song), create(db, song, "Newer")
        metadata_service.accept_suggestion(db, first.id, reviewed_by="tester"); db.commit()
        metadata_service.accept_suggestion(db, second.id, reviewed_by="tester"); db.commit()
        db.refresh(first); db.refresh(second); db.refresh(song)
        assert (first.status, second.status) == ("superseded", "accepted")
        assert song.title == "Original"
        assert second.applied_at is None


def test_reject_preserves_suggestion_for_audit():
    with SessionLocal() as db:
        song = add_song(db); item = create(db, song)
        metadata_service.reject_suggestion(db, item.id, reviewed_by="tester"); db.commit(); db.refresh(item)
        assert item.status == "rejected" and item.rejected_at is not None
        assert db.get(MetadataSuggestion, item.id) is not None


def test_invalid_field_and_entity_type_have_stable_codes():
    with SessionLocal() as db:
        song = add_song(db)
        for entity_type, field, code in (("playlist", "title", "metadata_invalid_entity_type"),
                                         ("song", "composer", "metadata_invalid_field")):
            try:
                metadata_service.create_suggestion(db, entity_type=entity_type, entity_id=song.id,
                    field_name=field, suggested_value="x", provider="test", confidence_level="high")
            except MetadataServiceError as exc:
                assert exc.code == code
            else:
                raise AssertionError("validation should fail")


def test_pagination_filtering_and_created_date():
    with SessionLocal() as db:
        song = add_song(db)
        create(db, song, "One", "alpha"); create(db, song, "Two", "beta")
        items, total = metadata_service.list_pending_suggestions(
            db, provider="alpha", field_name="title", created_from=datetime.now() - timedelta(days=1), limit=1, offset=0)
        assert total == 1 and items[0].provider == "alpha"


def test_missing_song_retains_suggestions_and_history():
    with SessionLocal() as db:
        song = add_song(db); suggestion = create(db, song)
        history = metadata_service.record_history(db, entity_type="song", entity_id=song.id,
            field_name="title", previous_value="Old", new_value="Original", provider="manual",
            provider_entity_id=None, confidence=1, job_id=None, change_source="manual",
            audio_file_modified=False, reversible=True, reversal_of_history_id=None)
        song.availability_status = "missing"; db.commit()
        assert db.get(MetadataSuggestion, suggestion.id) is not None
        assert db.get(MetadataHistory, history.id) is not None
        assert metadata_service.get_history(db, "song", song.id)[0][0].new_value == '"Original"'


def test_legacy_plain_text_history_values_serialize_without_error():
    with SessionLocal() as db:
        song = add_song(db)
        history = metadata_service.record_history(
            db, entity_type="song", entity_id=song.id, field_name="artwork",
            previous_value="embedded", new_value="missing", provider="file_tag_write",
            provider_entity_id=None, confidence=1, job_id=None, change_source="manual",
            audio_file_modified=False, reversible=True, reversal_of_history_id=None,
        )
        db.commit()

        serialized = serialize_history(history)

    assert serialized["previous_value"] == "embedded"
    assert serialized["new_value"] == "missing"


def test_metadata_api_errors_pagination_review_and_library_compatibility():
    with SessionLocal() as db:
        song = add_song(db); item = create(db, song)
        song_id, suggestion_id = song.id, item.id
    client = TestClient(app)
    assert client.get(f"/api/library/songs/{song_id}").status_code == 200
    page = client.get("/api/metadata/suggestions/pending", params={"provider": "test", "limit": 1}).json()
    assert page["pagination"] == {"total": 1, "limit": 1, "offset": 0, "has_more": False}
    assert client.get(f"/api/metadata/suggestions/{suggestion_id}").status_code == 200
    accepted = client.post(f"/api/metadata/suggestions/{suggestion_id}/accept", json={"reviewed_by": "api"})
    assert accepted.status_code == 200 and accepted.json()["status"] == "accepted"
    error = client.post(f"/api/metadata/suggestions/{suggestion_id}/reject", json={})
    assert error.status_code == 409
    assert error.json()["error"]["code"] == "metadata_invalid_transition"
    assert client.get("/api/metadata/suggestions/999999").json()["error"]["code"] == "metadata_suggestion_not_found"


def test_concurrent_acceptance_leaves_one_current_suggestion():
    with SessionLocal() as db:
        song = add_song(db); first, second = create(db, song, "One"), create(db, song, "Two")
        ids = (first.id, second.id)

    sessions = [SessionLocal(), SessionLocal()]
    # Establish both connections before the race so the global WAL setup itself
    # is not what the test races.
    for session in sessions:
        session.execute(select(MetadataSuggestion.id).limit(1)).all()

    def accept(pair):
        db, item_id = pair
        try:
            metadata_service.accept_suggestion(db, item_id, reviewed_by="race")
            db.commit()
            return "ok"
        except MetadataServiceError as exc:
            return exc.code
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(accept, zip(sessions, ids)))
    with SessionLocal() as db:
        current = db.scalars(select(MetadataSuggestion).where(MetadataSuggestion.status.in_(("accepted", "applied")))).all()
        assert len(current) == 1
