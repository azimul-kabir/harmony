from fastapi.testclient import TestClient

from app.database.models import Song
from app.database.session import SessionLocal
from app.main import app
from app.services.duplicate_detector import duplicate_detector


def _song(db, suffix, **values):
    song = Song(
        path=f"/music/{suffix}.flac",
        filename=f"{suffix}.flac",
        title=values.pop("title", "Signal"),
        artist=values.pop("artist", "Artist"),
        album=values.pop("album", "Album"),
        duration=values.pop("duration", 180),
        availability_status=values.pop("availability_status", "available"),
        **values,
    )
    db.add(song)
    db.flush()
    return song


def test_identity_tiers_are_explainable_and_quality_recommendation_is_read_only():
    with SessionLocal() as db:
        lower = _song(
            db, "lower", musicbrainz_recording_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            bitrate=128000, sample_rate=44100, file_size=3_000_000,
        )
        higher = _song(
            db, "higher", musicbrainz_recording_id="AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA",
            bitrate=1000000, sample_rate=96000, file_size=30_000_000,
        )
        db.commit()
        result = duplicate_detector.list(db)

    assert result["total"] == 1
    group = result["items"][0]
    assert group["tier"] == "exact"
    assert group["recommended_keep_id"] == higher.id
    assert group["song_ids"] == [lower.id, higher.id]
    assert group["evidence"][0]["field"] == "musicbrainz_recording_id"
    assert {song["availability_status"] for song in group["songs"]} == {"available"}


def test_fuzzy_candidates_require_duration_and_do_not_cross_external_id_conflicts():
    with SessionLocal() as db:
        first = _song(db, "first", title="The Signal!", artist="Ártist", duration=180)
        second = _song(db, "second", title="the signal", artist="artist", duration=182.5)
        _song(db, "conflict-a", title="Other", artist="Band", duration=200,
              isrc="USAAA0000001")
        _song(db, "conflict-b", title="Other", artist="Band", duration=201,
              isrc="USAAA0000002")
        db.commit()
        groups = duplicate_detector.detect(db)

    assert len(groups) == 1
    assert groups[0]["tier"] == "probable"
    assert groups[0]["song_ids"] == [first.id, second.id]
    assert "duration differs by 2.5s" in groups[0]["evidence"][0]["message"]


def test_possible_same_album_match_and_missing_files_are_opt_in():
    with SessionLocal() as db:
        available = _song(db, "available", duration=None)
        missing = _song(db, "missing", duration=None, availability_status="missing")
        db.commit()
        assert duplicate_detector.list(db)["total"] == 0
        included = duplicate_detector.list(db, include_missing=True)

    assert included["total"] == 1
    assert included["items"][0]["tier"] == "possible"
    assert included["items"][0]["song_ids"] == [available.id, missing.id]


def test_duplicate_api_supports_tier_filter_and_group_lookup():
    with SessionLocal() as db:
        _song(db, "one", isrc="USABC1234567")
        _song(db, "two", isrc="usabc1234567")
        db.commit()
    client = TestClient(app)

    page = client.get("/api/library/duplicates?tier=strong")
    assert page.status_code == 200
    payload = page.json()
    assert payload["total"] == 1 and payload["items"][0]["tier"] == "strong"

    detail = client.get(f"/api/library/duplicates/{payload['items'][0]['id']}")
    assert detail.status_code == 200
    assert detail.json()["song_count"] == 2
    assert client.get("/api/library/duplicates?tier=unsafe").status_code == 400
    assert client.get("/api/library/duplicates/dup-missing").status_code == 404
