from sqlalchemy import select

from app.database.models import MetadataIssue, Song
from app.database.session import SessionLocal
from app.services.metadata_health import RULES, metadata_health, normalize


EXPECTED_RULES = set("""missing_title missing_artist missing_album missing_album_artist
missing_track_number missing_year_or_release_date missing_genre missing_artwork missing_isrc
missing_musicbrainz_recording_id placeholder_title placeholder_artist placeholder_album
filename_derived_title invalid_track_number invalid_disc_number invalid_year
zero_or_implausible_duration suspicious_whitespace inconsistent_capitalization
inconsistent_album_artist inconsistent_album_title inconsistent_release_year inconsistent_genre
duplicate_track_number missing_track_numbers non_contiguous_track_numbers inconsistent_disc_totals
inconsistent_track_totals inconsistent_artwork probable_split_album
mixed_album_artist_and_track_artist_without_compilation_marker missing_musicbrainz_release_id
artist_name_variants suspicious_artist_spacing inconsistent_artist_capitalization
missing_musicbrainz_artist_id""".split())


def song(path: str, **values) -> Song:
    defaults = dict(filename=path.rsplit("/", 1)[-1], title="Title", artist="Artist",
                    album_artist="Artist", album="Album", track=1, disc=1, year=2020,
                    genre="Rock", duration=180, artwork_status="missing",
                    availability_status="available")
    defaults.update(values)
    return Song(path=path, **defaults)


def test_registry_contains_every_initial_rule_with_supported_metadata():
    assert set(RULES) == EXPECTED_RULES
    assert all(item["severity"] in {"info", "warning", "error", "critical"} for item in RULES.values())
    assert all(item["scope"] in {"song", "album", "artist"} for item in RULES.values())


def test_normalization_is_conservative_for_artists_features_and_versions():
    assert normalize("  THE  Cure ’ Live ", artist=True) == "cure ' live"
    assert normalize("Beyonc\N{LATIN SMALL LETTER E WITH ACUTE}") == normalize("Beyonce\N{COMBINING ACUTE ACCENT}")
    assert normalize("Song (Live)") != normalize("Song")
    assert "feat." in normalize("Artist feat. Guest", artist=True)


def test_song_rules_detect_missing_placeholder_invalid_and_suspicious_values():
    item = song("/music/UNKNOWN.mp3", title=" UNKNOWN ", artist="ARTIST", album="album",
                album_artist=None, track=0, disc=-1, year=999, genre=None, duration=0)
    rule_ids = {finding["rule_id"] for finding in metadata_health.detect_song(item)}
    assert {"missing_album_artist", "missing_genre", "missing_artwork", "missing_isrc",
            "missing_musicbrainz_recording_id", "placeholder_title", "placeholder_artist",
            "placeholder_album", "invalid_track_number",
            "invalid_disc_number", "invalid_year", "zero_or_implausible_duration",
            "suspicious_whitespace", "inconsistent_capitalization"} <= rule_ids
    derived = song("/music/Real Title.mp3", title="Real Title")
    assert "filename_derived_title" in {finding["rule_id"] for finding in metadata_health.detect_song(derived)}


def test_album_rules_handle_compilations_discs_duplicates_gaps_and_split_albums():
    with SessionLocal() as db:
        rows = [
            song("/music/a1.mp3", album="Shared", album_artist="Various Artists", artist="One", track=1, disc=1),
            song("/music/a2.mp3", album="Shared", album_artist="Various Artists", artist="Two", track=1, disc=1),
            song("/music/a3.mp3", album="Shared", album_artist="Various Artists", artist="Three", track=3, disc=2),
            song("/music/b1.mp3", album="Shared", album_artist="Other", artist="Other", track=1, disc=1),
        ]
        db.add_all(rows); db.commit()
        findings = metadata_health.analyze_album(db, metadata_health.album_key(rows[0]))
        rules = {finding.rule_id for finding in findings}
        assert {"duplicate_track_number", "non_contiguous_track_numbers", "probable_split_album",
                "missing_musicbrainz_release_id"} <= rules
        assert "mixed_album_artist_and_track_artist_without_compilation_marker" not in rules


def test_issue_reconciliation_reopens_resolved_and_preserves_ignored_and_missing_song():
    with SessionLocal() as db:
        item = song("/music/lifecycle.mp3", genre=None)
        db.add(item); db.commit(); db.refresh(item)
        metadata_health.analyze_song(db, item.id); db.commit()
        issue = db.scalar(select(MetadataIssue).where(MetadataIssue.rule_id == "missing_genre"))
        original_id = issue.id
        item.genre = "Rock"; metadata_health.analyze_song(db, item.id); db.commit(); db.refresh(issue)
        assert issue.status == "resolved"
        item.genre = None; metadata_health.analyze_song(db, item.id); db.commit(); db.refresh(issue)
        assert issue.id == original_id and issue.status == "open"
        metadata_health.set_status(db, issue.id, "ignored"); metadata_health.analyze_song(db, item.id); db.commit(); db.refresh(issue)
        assert issue.status == "ignored"
        metadata_health.set_status(db, issue.id, "open"); db.commit(); db.refresh(issue)
        assert issue.status == "open"
        item.availability_status = "missing"; db.commit()
        assert db.get(MetadataIssue, original_id) is not None
        assert metadata_health.score(db)["inputs"]["included_open_issues"] == 0


def test_filter_pagination_summary_and_score_inputs():
    with SessionLocal() as db:
        first, second = song("/music/one.mp3", genre=None), song("/music/two.mp3", genre=None)
        db.add_all([first, second]); db.commit()
        metadata_health.analyze_song(db, first.id); metadata_health.analyze_song(db, second.id); db.commit()
        rows, total = metadata_health.list(db, rule_id="missing_genre", status="open", limit=1, offset=1)
        assert total == 2 and len(rows) == 1
        summary = metadata_health.summary(db)
        assert {"rule", "severity", "status", "entity_type", "album", "artist"} <= set(summary["counts"])
        assert 0 <= summary["score"]["score"] <= 100
        assert summary["score"]["diagnostic_only"] is True


def test_metadata_summary_and_score_share_included_open_record_scope():
    with SessionLocal() as db:
        available = song("/music/available.mp3", genre=None)
        missing = song("/music/missing.mp3", genre=None)
        db.add_all([available, missing]); db.commit()
        metadata_health.analyze_song(db, available.id)
        metadata_health.analyze_song(db, missing.id)
        db.commit()
        missing.availability_status = "missing"
        ignored = db.scalar(select(MetadataIssue).where(MetadataIssue.song_id == available.id, MetadataIssue.rule_id == "missing_genre"))
        metadata_health.set_status(db, ignored.id, "ignored")
        db.commit()
        summary = metadata_health.summary(db)
        severity_total = sum(row["count"] for row in summary["counts"]["severity"])
        assert severity_total == summary["score"]["inputs"]["included_open_issues"]
        assert summary["counts"]["status"] == [{"value": "open", "count": severity_total}]
        assert summary["score"]["inputs"]["ignored_issues"] >= 1
        assert summary["score"]["score"] < 100


def test_metadata_score_boundaries_and_severity_penalties():
    with SessionLocal() as db:
        assert metadata_health.score(db)["score"] == 100
        song_row = song("/music/scored.mp3")
        db.add(song_row); db.commit()

        def add_issue(severity: str, number: int) -> None:
            db.add(MetadataIssue(
                identity_key=f"score-{severity}-{number}", rule_id="missing_genre", rule_version="1",
                entity_type="song", entity_id=str(song_row.id), song_id=song_row.id,
                severity=severity, status="open", title="Missing genre", explanation="Missing genre",
            ))
            db.commit()

        add_issue("warning", 1)
        warning_score = metadata_health.score(db)["score"]
        assert 0 <= warning_score < 100
        add_issue("error", 1)
        error_score = metadata_health.score(db)["score"]
        assert error_score <= warning_score
        add_issue("critical", 1)
        critical_score = metadata_health.score(db)["score"]
        assert critical_score <= error_score
        for number in range(2, 20):
            add_issue("critical", number)
        assert metadata_health.score(db)["score"] == 0


def test_full_analysis_resolves_removed_album_and_artist_projections_and_keeps_audit_history():
    with SessionLocal() as db:
        row = song("/music/projection.mp3", album="Album", artist="Artist", album_artist="Artist")
        db.add(row); db.commit()
        album_key = metadata_health.album_key(row)
        artist_key = metadata_health.artist_key(row.artist)
        metadata_health.analyze_full(db); db.commit()
        album_issue = db.scalar(select(MetadataIssue).where(MetadataIssue.entity_type == "album", MetadataIssue.entity_id == album_key))
        artist_issue = db.scalar(select(MetadataIssue).where(MetadataIssue.entity_type == "artist", MetadataIssue.entity_id == artist_key))
        assert album_issue.status == artist_issue.status == "open"
        row.availability_status = "missing"
        metadata_health.analyze_full(db); db.commit()
        db.refresh(album_issue); db.refresh(artist_issue)
        assert album_issue.status == artist_issue.status == "resolved"
        assert metadata_health.list(db, status="resolved", limit=50)[1] >= 2
        row.availability_status = "available"
        metadata_health.analyze_full(db); db.commit()
        db.refresh(album_issue); db.refresh(artist_issue)
        assert album_issue.status == artist_issue.status == "open"


def test_full_analysis_does_not_resolve_projections_when_projection_analysis_fails(monkeypatch):
    with SessionLocal() as db:
        db.add(MetadataIssue(identity_key="album-stale", rule_id="missing_musicbrainz_release_id", rule_version="1", entity_type="album", entity_id="gone", album_key="gone", severity="info", status="open", title="Album", explanation="Album"))
        db.commit()
        monkeypatch.setattr(metadata_health, "analyze_projections", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("analysis failed")))
        try:
            metadata_health.analyze_full(db)
        except RuntimeError:
            pass
        else:
            raise AssertionError("projection failure should be propagated")
        assert db.scalar(select(MetadataIssue.status).where(MetadataIssue.identity_key == "album-stale")) == "open"


def test_included_open_list_matches_score_scope_and_excludes_missing_song_records():
    with SessionLocal() as db:
        available = song("/music/included.mp3")
        missing = song("/music/excluded.mp3", availability_status="missing")
        db.add_all([available, missing]); db.commit()
        db.add_all([
            MetadataIssue(identity_key="included", rule_id="missing_genre", rule_version="1", entity_type="song", entity_id=str(available.id), song_id=available.id, severity="warning", status="open", title="Included", explanation="Included"),
            MetadataIssue(identity_key="excluded", rule_id="missing_genre", rule_version="1", entity_type="song", entity_id=str(missing.id), song_id=missing.id, severity="warning", status="open", title="Excluded", explanation="Excluded"),
        ])
        db.commit()
        visible, total = metadata_health.list(db, status="open", included_only=True, limit=50)
        summary = metadata_health.summary(db)
        assert total == len(visible) == summary["score"]["inputs"]["included_open_issues"] == 1
        assert visible[0].identity_key == "included"
