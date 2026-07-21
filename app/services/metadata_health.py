"""Provider-neutral metadata diagnostics over the persistent Library Index."""
from __future__ import annotations

import hashlib
import json
import re
import threading
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.time import utcnow_naive
from app.database.models import MetadataIssue, Song

RULE_VERSION = "1"
MAX_EVIDENCE_ITEMS = 20
MAX_EVIDENCE_BYTES = 2_000
PLACEHOLDERS = {"unknown", "unknown artist", "unknown album", "untitled track", "track", "artist", "album", "n/a", "none"}
COMPILATION_ARTISTS = {"various", "various artists", "va"}


@dataclass(frozen=True)
class RuleDefinition:
    id: str
    scope: str
    severity: str
    title: str
    explanation: str
    suggested_action: str
    field_name: str | None = None
    version: str = RULE_VERSION


def _rule(rule_id: str, scope: str, severity: str, field: str | None = None) -> RuleDefinition:
    title = rule_id.replace("_", " ").capitalize()
    return RuleDefinition(
        rule_id, scope, severity, title,
        f"Indexed canonical metadata indicates {rule_id.replace('_', ' ')}.",
        "Review the canonical metadata in Harmony before making a correction.", field,
    )


_RULE_SPECS = {
    "song": {
        "warning": "missing_title missing_artist missing_album missing_album_artist missing_track_number missing_year_or_release_date missing_genre missing_artwork placeholder_title placeholder_artist placeholder_album filename_derived_title suspicious_whitespace inconsistent_capitalization",
        "error": "invalid_track_number invalid_disc_number invalid_year zero_or_implausible_duration",
        "info": "missing_isrc missing_musicbrainz_recording_id",
    },
    "album": {
        "warning": "inconsistent_album_artist inconsistent_album_title inconsistent_release_year inconsistent_genre duplicate_track_number missing_track_numbers non_contiguous_track_numbers inconsistent_disc_totals inconsistent_track_totals inconsistent_artwork probable_split_album mixed_album_artist_and_track_artist_without_compilation_marker",
        "info": "missing_musicbrainz_release_id",
    },
    "artist": {
        "warning": "artist_name_variants suspicious_artist_spacing inconsistent_artist_capitalization",
        "info": "missing_musicbrainz_artist_id",
    },
}
RULE_DEFINITIONS = {
    rule_id: _rule(rule_id, scope, severity)
    for scope, severities in _RULE_SPECS.items()
    for severity, names in severities.items()
    for rule_id in names.split()
}
# Compatibility export used by the API and any third-party extensions.
RULES = {key: {"severity": value.severity, "scope": value.scope} for key, value in RULE_DEFINITIONS.items()}


def normalize(value: str | None, *, artist: bool = False) -> str | None:
    """Normalize conservatively for comparison; never use this to rewrite tags."""
    if value is None:
        return None
    result = unicodedata.normalize("NFKC", str(value)).strip()
    result = re.sub(r"\s+", " ", result)
    result = re.sub(r"[’‘]", "'", result)
    result = re.sub(r"[‐‑‒–—―]", "-", result)
    result = re.sub(r"\s*([&/+])\s*", r" \1 ", result)
    result = re.sub(r"\s+", " ", result).casefold()
    if artist and result.startswith("the "):
        result = result[4:]
    return result


def _bounded_evidence(value: dict | None) -> tuple[dict, str]:
    safe: dict = {}
    for key, item in (value or {}).items():
        if isinstance(item, (list, tuple, set)):
            safe[key] = [str(part)[:200] for part in list(item)[:MAX_EVIDENCE_ITEMS]]
        elif isinstance(item, (str, int, float, bool)) or item is None:
            safe[key] = item if not isinstance(item, str) else item[:500]
    encoded = json.dumps(safe, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if len(encoded.encode()) > MAX_EVIDENCE_BYTES:
        safe = {"truncated": True, "keys": sorted(safe)[:MAX_EVIDENCE_ITEMS]}
        encoded = json.dumps(safe, separators=(",", ":"))
    return safe, encoded


class MetadataHealthService:
    def __init__(self, *, max_duration_seconds: float = 8 * 3600,
                 max_track_number: int = 999, max_disc_number: int = 99,
                 allowed_future_years: int = 1) -> None:
        self.rules = dict(RULE_DEFINITIONS)
        self._reconcile_lock = threading.RLock()
        self.max_duration_seconds = max_duration_seconds
        self.max_track_number = max_track_number
        self.max_disc_number = max_disc_number
        self.allowed_future_years = allowed_future_years

    def register_rule(self, definition: RuleDefinition) -> None:
        if definition.id in self.rules:
            raise ValueError(f"Metadata health rule already registered: {definition.id}")
        self.rules[definition.id] = definition

    @staticmethod
    def album_key(song: Song) -> str:
        return f"{normalize(song.album_artist or song.artist, artist=True) or ''}::{normalize(song.album) or ''}"

    @staticmethod
    def artist_key(value: str | None) -> str:
        return normalize(value, artist=True) or ""

    def _finding(self, rule_id: str, entity_type: str, entity_id: str | int, *, field: str | None = None,
                 value=None, song: Song | None = None, album: str | None = None, artist: str | None = None,
                 evidence: dict | None = None, normalized_value: str | None = None) -> dict:
        definition = self.rules[rule_id]
        safe_evidence, encoded = _bounded_evidence(evidence)
        identity_evidence = json.dumps(safe_evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        identity = hashlib.sha256(
            "|".join((rule_id, definition.version, entity_type, str(entity_id), field or "", identity_evidence)).encode()
        ).hexdigest()
        return {
            "identity_key": identity, "rule_id": rule_id, "rule_version": definition.version,
            "entity_type": entity_type, "entity_id": str(entity_id), "field_name": field or definition.field_name,
            "current_value": str(value)[:2000] if value is not None else None,
            "normalized_value": normalized_value if normalized_value is not None else (normalize(str(value)) if value is not None else None),
            "song_id": song.id if song else None, "album_key": album, "artist_key": artist,
            "severity": definition.severity, "title": definition.title, "explanation": definition.explanation,
            "suggested_action": definition.suggested_action, "automatically_repairable": False, "evidence": encoded,
        }

    @staticmethod
    def _blank(value) -> bool:
        return value is None or (isinstance(value, str) and not value.strip())

    def detect_song(self, song: Song) -> list[dict]:
        found: list[dict] = []
        album_key = self.album_key(song) if song.album else None
        artist_key = self.artist_key(song.artist) if song.artist else None
        missing = {
            "title": song.title, "artist": song.artist, "album": song.album,
            "album_artist": song.album_artist, "track_number": song.track,
            "year_or_release_date": song.year, "genre": song.genre,
        }
        for field, value in missing.items():
            if self._blank(value):
                found.append(self._finding(f"missing_{field}", "song", song.id, field=field, value=value,
                                           song=song, album=album_key, artist=artist_key))
        for rule_id, field, value in (
            ("missing_artwork", "artwork", song.artwork_id), ("missing_isrc", "isrc", song.isrc),
            ("missing_musicbrainz_recording_id", "musicbrainz_recording_id", song.musicbrainz_recording_id),
        ):
            if self._blank(value):
                found.append(self._finding(rule_id, "song", song.id, field=field, song=song, album=album_key, artist=artist_key))
        for field in ("title", "artist", "album"):
            value = getattr(song, field)
            normalized = normalize(value)
            if value and normalized in PLACEHOLDERS:
                found.append(self._finding(f"placeholder_{field}", "song", song.id, field=field, value=value, song=song))
            if value and (value != value.strip() or bool(re.search(r"\s{2,}", value))):
                found.append(self._finding("suspicious_whitespace", "song", song.id, field=field, value=value, song=song,
                                           evidence={"kind": "leading_trailing" if value != value.strip() else "repeated_internal"}))
            if value and any(char.isalpha() for char in value) and (value.isupper() or value.islower()) and len(value) > 3:
                found.append(self._finding("inconsistent_capitalization", "song", song.id, field=field, value=value, song=song))
        if song.title:
            stem = Path(song.filename or "").stem
            candidates = {normalize(stem), normalize(re.sub(r"^\s*\d+[ ._-]+", "", stem))}
            if normalize(song.title) in candidates and normalize(song.title) not in PLACEHOLDERS:
                found.append(self._finding("filename_derived_title", "song", song.id, field="title", value=song.title, song=song,
                                           evidence={"filename": (song.filename or "")[:200]}))
        if song.track is not None and (not isinstance(song.track, int) or song.track <= 0 or song.track > self.max_track_number):
            found.append(self._finding("invalid_track_number", "song", song.id, field="track_number", value=song.track, song=song))
        if song.disc is not None and (not isinstance(song.disc, int) or song.disc <= 0 or song.disc > self.max_disc_number):
            found.append(self._finding("invalid_disc_number", "song", song.id, field="disc_number", value=song.disc, song=song))
        if song.year is not None and (not isinstance(song.year, int) or not 1000 <= song.year <= datetime.now().year + self.allowed_future_years):
            found.append(self._finding("invalid_year", "song", song.id, field="year", value=song.year, song=song))
        if song.duration is not None and (song.duration <= 0 or song.duration > self.max_duration_seconds):
            found.append(self._finding("zero_or_implausible_duration", "song", song.id, field="duration", value=song.duration, song=song))
        return found

    def reconcile(self, db: Session, findings: Sequence[dict], *, scope: tuple[str, str | int | Sequence[int]] | None = None,
                  job_id: int | None = None) -> list[MetadataIssue]:
        with self._reconcile_lock:
            return self._reconcile_locked(db, findings, scope=scope, job_id=job_id)

    def _reconcile_locked(self, db: Session, findings: Sequence[dict], *,
                          scope: tuple[str, str | int | Sequence[int]] | None = None,
                          job_id: int | None = None) -> list[MetadataIssue]:
        now = utcnow_naive()
        identities = {item["identity_key"] for item in findings}
        clauses = []
        if scope:
            entity_ids = scope[1]
            entity_clause = (MetadataIssue.entity_id.in_([str(value) for value in entity_ids])
                             if isinstance(entity_ids, (list, tuple, set)) else MetadataIssue.entity_id == str(entity_ids))
            clauses = [MetadataIssue.entity_type == scope[0], entity_clause]
        elif job_id is not None:
            clauses = [MetadataIssue.status == "open"]
        existing = list(db.scalars(select(MetadataIssue).where(*clauses)).all()) if clauses else []
        by_identity = {item.identity_key: item for item in existing}
        missing_keys = identities - set(by_identity)
        if missing_keys:
            keys = list(missing_keys)
            for start in range(0, len(keys), 500):
                for item in db.scalars(select(MetadataIssue).where(MetadataIssue.identity_key.in_(keys[start:start + 500]))):
                    by_identity[item.identity_key] = item
        if scope:
            for issue in existing:
                if issue.identity_key not in identities and issue.status == "open":
                    issue.status, issue.resolved_at = "resolved", now
        persisted = []
        for data in findings:
            issue = by_identity.get(data["identity_key"])
            if issue is None:
                issue = MetadataIssue(**data, first_detected_at=now, last_detected_at=now, detection_job_id=job_id)
                db.add(issue)
            else:
                for key, value in data.items():
                    setattr(issue, key, value)
                issue.last_detected_at, issue.detection_job_id = now, job_id
                if issue.status == "resolved":
                    issue.status, issue.resolved_at = "open", None
            persisted.append(issue)
        return persisted

    def analyze_song(self, db: Session, song_id: int, job_id: int | None = None) -> list[MetadataIssue]:
        song = db.get(Song, song_id)
        if song is None or song.availability_status != "available":
            raise LookupError("Song not found")
        return self.reconcile(db, self.detect_song(song), scope=("song", song.id), job_id=job_id)

    @staticmethod
    def _variants(rows: Sequence[Song], attr: str, *, artist: bool = False) -> dict[str, set[str]]:
        result: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            value = getattr(row, attr, None)
            if value is not None and str(value).strip():
                result[normalize(str(value), artist=artist) or ""].add(str(value))
        return result

    def analyze_album_rows(self, db: Session, key: str, rows: Sequence[Song], job_id: int | None = None,
                           sibling_projection_count: int = 1) -> list[MetadataIssue]:
        findings: list[dict] = []
        for rule_id, attr in (("inconsistent_album_artist", "album_artist"), ("inconsistent_album_title", "album"),
                              ("inconsistent_release_year", "year"), ("inconsistent_genre", "genre")):
            variants = self._variants(rows, attr, artist=attr == "album_artist")
            raw_values = {value for group in variants.values() for value in group}
            differs = len(variants) > 1 or (attr in {"album", "album_artist"} and len(raw_values) > 1)
            if differs:
                values = sorted(value for group in variants.values() for value in group)
                findings.append(self._finding(rule_id, "album", key, field=attr, album=key, evidence={"variants": values}))
        by_disc: dict[int, list[Song]] = defaultdict(list)
        for song in rows:
            by_disc[song.disc or 1].append(song)
        duplicates = sorted(f"{disc}:{track}" for disc, disc_rows in by_disc.items()
                            for track, count in Counter(s.track for s in disc_rows if s.track and s.track > 0).items() if count > 1)
        if duplicates:
            findings.append(self._finding("duplicate_track_number", "album", key, field="track_number", album=key,
                                          evidence={"disc_tracks": duplicates}))
        if any(song.track is None for song in rows):
            findings.append(self._finding("missing_track_numbers", "album", key, field="track_number", album=key,
                                          evidence={"missing_count": sum(song.track is None for song in rows)}))
        gaps = []
        for disc, disc_rows in by_disc.items():
            tracks = sorted({song.track for song in disc_rows if song.track and song.track > 0})
            if tracks and tracks != list(range(1, max(tracks) + 1)):
                gaps.extend(f"{disc}:{number}" for number in sorted(set(range(1, max(tracks) + 1)) - set(tracks)))
        if gaps:
            findings.append(self._finding("non_contiguous_track_numbers", "album", key, field="track_number", album=key,
                                          evidence={"missing_disc_tracks": gaps}))
        discs = {song.disc for song in rows if song.disc and song.disc > 0}
        disc_totals = {song.disc_total for song in rows if song.disc_total is not None}
        if len(discs) > 1 and (any(song.disc is None for song in rows) or discs != set(range(1, max(discs) + 1))
                               or len(disc_totals) > 1 or (disc_totals and max(discs) > next(iter(disc_totals)))):
            findings.append(self._finding("inconsistent_disc_totals", "album", key, field="disc_number", album=key,
                                          evidence={"discs": sorted(discs), "declared_totals": sorted(disc_totals)}))
        track_totals = {song.track_total for song in rows if song.track_total is not None}
        if len(track_totals) > 1 or any(song.track_total is not None and song.track and song.track > song.track_total for song in rows):
            findings.append(self._finding("inconsistent_track_totals", "album", key, field="track_total", album=key,
                                          evidence={"declared_totals": sorted(track_totals)}))
        artwork = {(song.artwork_id, normalize(song.cover_url)) for song in rows if song.artwork_id or song.cover_url}
        if len(artwork) > 1:
            findings.append(self._finding("inconsistent_artwork", "album", key, field="artwork", album=key,
                                          evidence={"variant_count": len(artwork)}))
        album_artists = self._variants(rows, "album_artist", artist=True)
        track_artists = self._variants(rows, "artist", artist=True)
        compilation = any(song.compilation is True for song in rows) or any(name in COMPILATION_ARTISTS for name in album_artists)
        if len(track_artists) > 1 and len(album_artists) == 1 and not compilation:
            findings.append(self._finding("mixed_album_artist_and_track_artist_without_compilation_marker", "album", key,
                                          field="artist", album=key, evidence={"track_artist_count": len(track_artists)}))
        # Split album: same normalized title appears under multiple close album-artist projections.
        if sibling_projection_count > 1:
            findings.append(self._finding("probable_split_album", "album", key, field="album", album=key,
                                          evidence={"projection_count": sibling_projection_count}))
        if not any(song.musicbrainz_release_id for song in rows):
            findings.append(self._finding("missing_musicbrainz_release_id", "album", key, field="musicbrainz_release_id", album=key))
        return self.reconcile(db, findings, scope=("album", key), job_id=job_id)

    def analyze_artist_rows(self, db: Session, key: str, rows: Sequence[Song], job_id: int | None = None) -> list[MetadataIssue]:
        findings: list[dict] = []
        spellings = {song.artist for song in rows if song.artist}
        comparison = {normalize(value, artist=True) for value in spellings}
        if len(spellings) > 1 and len(comparison) == 1:
            findings.append(self._finding("artist_name_variants", "artist", key, field="artist", artist=key,
                                          evidence={"variants": sorted(spellings)}))
            if len({unicodedata.normalize("NFKC", value).strip().casefold() for value in spellings}) == 1:
                findings.append(self._finding("inconsistent_artist_capitalization", "artist", key, field="artist", artist=key,
                                              evidence={"variants": sorted(spellings)}))
        if any(value != value.strip() or re.search(r"\s{2,}", value) for value in spellings):
            findings.append(self._finding("suspicious_artist_spacing", "artist", key, field="artist", artist=key,
                                          evidence={"variants": sorted(spellings)}))
        if not any(song.musicbrainz_artist_id for song in rows):
            findings.append(self._finding("missing_musicbrainz_artist_id", "artist", key, field="musicbrainz_artist_id", artist=key))
        return self.reconcile(db, findings, scope=("artist", key), job_id=job_id)

    def analyze_album(self, db: Session, key: str, job_id: int | None = None) -> list[MetadataIssue]:
        all_rows = list(db.scalars(select(Song).where(Song.availability_status == "available")).all())
        rows = [song for song in all_rows if self.album_key(song) == key]
        if not rows:
            raise LookupError("Album not found")
        title = normalize(rows[0].album)
        sibling_count = len({self.album_key(song) for song in all_rows if normalize(song.album) == title})
        return self.analyze_album_rows(db, key, rows, job_id, sibling_count)

    def analyze_artist(self, db: Session, key: str, job_id: int | None = None) -> list[MetadataIssue]:
        rows = [song for song in db.scalars(select(Song).where(Song.availability_status == "available")).all()
                if self.artist_key(song.artist) == key]
        if not rows:
            raise LookupError("Artist not found")
        return self.analyze_artist_rows(db, key, rows, job_id)

    def analyze_projections(self, db: Session, songs: Sequence[Song], job_id: int | None = None) -> tuple[int, int]:
        albums: dict[str, list[Song]] = defaultdict(list)
        artists: dict[str, list[Song]] = defaultdict(list)
        for song in songs:
            if song.album:
                albums[self.album_key(song)].append(song)
            if song.artist:
                artists[self.artist_key(song.artist)].append(song)
        title_projection_counts: dict[str, set[str]] = defaultdict(set)
        for album_key, rows in albums.items():
            title_projection_counts[normalize(rows[0].album) or ""].add(album_key)
        for key, rows in albums.items():
            self.analyze_album_rows(db, key, rows, job_id, len(title_projection_counts[normalize(rows[0].album) or ""]))
        for key, rows in artists.items():
            self.analyze_artist_rows(db, key, rows, job_id)
        return len(albums), len(artists)

    _analyze_projections = analyze_projections

    def analyze_full(self, db: Session, job_id: int | None = None) -> int:
        songs = list(db.scalars(select(Song).where(Song.availability_status == "available")).all())
        all_findings: list[dict] = []
        for song in songs:
            all_findings.extend(self.detect_song(song))
        self.reconcile(db, all_findings, job_id=job_id)
        self.analyze_projections(db, songs, job_id)
        detected = {item["identity_key"] for item in all_findings}
        for issue in db.scalars(select(MetadataIssue).where(MetadataIssue.status == "open")):
            if issue.entity_type == "song" and issue.identity_key not in detected:
                issue.status, issue.resolved_at = "resolved", utcnow_naive()
        return len(songs)

    def list(self, db: Session, **filters):
        limit, offset = filters.pop("limit", 50), filters.pop("offset", 0)
        query = select(MetadataIssue)
        clauses = []
        ranges = {"first_detected_from": ("first_detected_at", ">="), "first_detected_to": ("first_detected_at", "<="),
                  "last_detected_from": ("last_detected_at", ">="), "last_detected_to": ("last_detected_at", "<=")}
        search = filters.pop("search", None)
        for key, value in filters.items():
            if value is None:
                continue
            if key in ranges:
                column, operator = ranges[key]
                target = getattr(MetadataIssue, column)
                clauses.append(target >= value if operator == ">=" else target <= value)
            elif hasattr(MetadataIssue, key):
                clauses.append(getattr(MetadataIssue, key) == value)
        if search:
            pattern = f"%{search[:200]}%"
            clauses.append(or_(MetadataIssue.title.ilike(pattern), MetadataIssue.explanation.ilike(pattern),
                               MetadataIssue.album_key.ilike(pattern), MetadataIssue.artist_key.ilike(pattern)))
        query = query.where(*clauses)
        total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = list(db.scalars(query.order_by(MetadataIssue.last_detected_at.desc(), MetadataIssue.id.desc())
                               .offset(offset).limit(limit)))
        return rows, int(total)

    def get(self, db: Session, issue_id: int) -> MetadataIssue:
        issue = db.get(MetadataIssue, issue_id)
        if issue is None:
            raise LookupError("Metadata issue not found")
        return issue

    def set_status(self, db: Session, issue_id: int, status: str) -> MetadataIssue:
        issue = self.get(db, issue_id)
        now = utcnow_naive()
        if status == "ignored":
            issue.status, issue.ignored_at, issue.resolved_at = status, now, None
        elif status == "open":
            issue.status, issue.ignored_at, issue.resolved_at = status, None, None
        elif status == "resolved":
            issue.status, issue.resolved_at = status, now
        return issue

    def resolve_verified(self, db: Session, issue_id: int) -> MetadataIssue:
        return self.set_status(db, issue_id, "resolved")

    def summary(self, db: Session) -> dict:
        dimensions = {}
        for name, column in (("rule", MetadataIssue.rule_id), ("severity", MetadataIssue.severity),
                             ("status", MetadataIssue.status), ("entity_type", MetadataIssue.entity_type),
                             ("album", MetadataIssue.album_key), ("artist", MetadataIssue.artist_key)):
            rows = db.execute(select(column, func.count()).group_by(column)).all()
            dimensions[name] = [{"value": value, "count": count} for value, count in rows if value is not None]
        return {"counts": dimensions, "score": self.score(db)}

    def score(self, db: Session) -> dict:
        weights = {"info": 0.25, "warning": 2.0, "error": 6.0, "critical": 12.0}
        available_ids = select(Song.id).where(Song.availability_status == "available")
        rows = list(db.scalars(select(MetadataIssue).where(
            MetadataIssue.status == "open",
            or_(MetadataIssue.entity_type != "song", MetadataIssue.song_id.in_(available_ids)),
        )))
        grouped: Counter[tuple[str, str]] = Counter()
        by_severity = Counter()
        for issue in rows:
            penalty = weights[issue.severity]
            grouped[(issue.entity_type, issue.album_key or issue.artist_key or issue.entity_id)] += penalty
            by_severity[issue.severity] += 1
        entity_cap = 20.0
        penalty = round(sum(min(value, entity_cap) for value in grouped.values()), 2)
        available = int(db.scalar(select(func.count()).select_from(Song).where(Song.availability_status == "available")) or 0)
        budget = max(available * 10.0, 1.0)
        score = max(0, min(100, round(100 * (1 - min(penalty, budget) / budget))))
        ignored = int(db.scalar(select(func.count()).select_from(MetadataIssue).where(MetadataIssue.status == "ignored")) or 0)
        return {"score": score, "inputs": {"available_songs": available, "included_open_issues": len(rows),
                "ignored_issues": ignored, "issues_by_severity": dict(by_severity), "weighted_penalty": penalty,
                "penalty_budget": budget, "weights": weights, "per_entity_cap": entity_cap}, "diagnostic_only": True}


metadata_health = MetadataHealthService()


def serialize_issue(issue: MetadataIssue) -> dict:
    data = {key: getattr(issue, key) for key in (
        "id", "rule_id", "rule_version", "entity_type", "entity_id", "song_id", "album_key", "artist_key",
        "field_name", "severity", "status", "title", "explanation", "current_value", "normalized_value",
        "suggested_action", "automatically_repairable", "first_detected_at", "last_detected_at", "resolved_at",
        "ignored_at", "detection_job_id")}
    try:
        data["evidence"] = json.loads(issue.evidence or "{}")
    except (TypeError, json.JSONDecodeError):
        data["evidence"] = {"unavailable": True}
    return data
