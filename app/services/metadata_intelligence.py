"""Provider-independent metadata review and audit service."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
import re
import unicodedata

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import utcnow_naive
from app.database.models import (MetadataApplicationBatch, MetadataApplicationLock,
    MetadataDiscoveryLock, MetadataHistory, MetadataSuggestion, Song, Task)
from app.domain.task import TaskStatus, TaskType
from app.services.task_service import create_task, record_item_failure
from app.services.library_search import library_search
from app.services.metadata_health import metadata_health

ENTITY_TYPES = frozenset({"song", "album", "artist"})
METADATA_FIELDS = frozenset({
    "title", "artist", "album_artist", "album", "track_number", "total_tracks",
    "disc_number", "total_discs", "release_date", "original_release_date", "year",
    "genre", "isrc", "musicbrainz_recording_id", "musicbrainz_release_id",
    "musicbrainz_release_group_id", "musicbrainz_artist_id",
    "musicbrainz_release_artist_id", "artwork_source",
})
STATUSES = frozenset({"pending", "accepted", "rejected", "superseded", "applied", "apply_failed"})
CONFIDENCE_LEVELS = frozenset({"exact", "high", "medium", "low", "rejected"})
CURRENT_STATUSES = ("accepted", "applied")
MAX_VALUE_BYTES = 4096
MAX_EVIDENCE_BYTES = 8192
APPLICABLE_FIELDS = METADATA_FIELDS - {"artwork_source"}
FIELD_COLUMNS = {"track_number": "track", "total_tracks": "track_total", "disc_number": "disc", "total_discs": "disc_total"}
MAX_TEXT_LENGTH = 500


@dataclass
class MetadataServiceError(Exception):
    code: str
    message: str
    status_code: int = 400

    def __str__(self) -> str:
        return self.message


def _json_dump(value: Any, *, limit: int) -> str | None:
    if value is None:
        return None
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise MetadataServiceError("metadata_invalid_json", "Metadata values and evidence must be JSON-compatible.") from exc
    if len(encoded.encode("utf-8")) > limit:
        raise MetadataServiceError("metadata_payload_too_large", "Metadata value or evidence exceeds the bounded storage limit.", 413)
    return encoded


def _json_load(value: str | None) -> Any:
    """Decode stored JSON while preserving values written by older releases.

    Metadata history predates JSON-encoded values, so existing databases can
    contain plain strings such as ``embedded``.  Returning those strings keeps
    the history API available instead of turning one legacy record into a 500.
    """
    if value is None:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


class MetadataService:
    def _validate_entity(self, entity_type: str, entity_id: int, db: Session, *, require_existing: bool = True) -> None:
        if entity_type not in ENTITY_TYPES:
            raise MetadataServiceError("metadata_invalid_entity_type", "Unsupported metadata entity type.")
        if entity_id < 1:
            raise MetadataServiceError("metadata_invalid_entity_id", "Entity ID must be positive.")
        if require_existing and entity_type == "song" and db.get(Song, entity_id) is None:
            raise MetadataServiceError("metadata_song_not_found", "Song not found.", 404)

    def _validate_field(self, field_name: str) -> None:
        if field_name not in METADATA_FIELDS:
            raise MetadataServiceError("metadata_invalid_field", "Unsupported metadata field.")

    def canonical_metadata(self, db: Session, entity_type: str, entity_id: int) -> dict[str, Any]:
        self._validate_entity(entity_type, entity_id, db)
        if entity_type != "song":
            return {field: None for field in sorted(METADATA_FIELDS)}
        song = db.get(Song, entity_id)
        assert song is not None
        values = {field: None for field in METADATA_FIELDS}
        values.update({
            "title": song.title, "artist": song.artist, "album_artist": song.album_artist,
            "album": song.album, "track_number": song.track, "disc_number": song.disc,
            "total_tracks": song.track_total, "total_discs": song.disc_total,
            "year": song.year, "genre": song.genre, "isrc": song.isrc,
            "release_date": song.release_date, "original_release_date": song.original_release_date,
            "musicbrainz_recording_id": song.musicbrainz_recording_id,
            "musicbrainz_release_id": song.musicbrainz_release_id,
            "musicbrainz_release_group_id": song.musicbrainz_release_group_id,
            "musicbrainz_artist_id": song.musicbrainz_artist_id,
            "musicbrainz_release_artist_id": song.musicbrainz_release_artist_id,
            "artwork_source": song.artwork.source if song.artwork else None,
        })
        return {field: values[field] for field in sorted(values)}

    def create_suggestion(self, db: Session, *, entity_type: str, entity_id: int,
                          field_name: str, suggested_value: Any, provider: str,
                          confidence_level: str, confidence: float | None = None,
                          current_value: Any = None, provider_entity_id: str | None = None,
                          match_explanation: str | None = None, positive_evidence: Any = None,
                          conflicting_evidence: Any = None, created_by_job_id: int | None = None,
                          discovery_id: int | None = None, match_result_id: int | None = None,
                          reviewed_by: str | None = None) -> MetadataSuggestion:
        self._validate_entity(entity_type, entity_id, db)
        self._validate_field(field_name)
        provider = provider.strip()
        if not provider or len(provider) > 80:
            raise MetadataServiceError("metadata_invalid_provider", "Provider is required and must be at most 80 characters.")
        if confidence_level not in CONFIDENCE_LEVELS:
            raise MetadataServiceError("metadata_invalid_confidence_level", "Unsupported confidence level.")
        if confidence is not None and not 0 <= confidence <= 1:
            raise MetadataServiceError("metadata_invalid_confidence", "Confidence must be between 0 and 1.")
        if match_explanation and len(match_explanation) > 1000:
            raise MetadataServiceError("metadata_payload_too_large", "Match explanation exceeds 1000 characters.", 413)
        canonical = self.canonical_metadata(db, entity_type, entity_id)
        suggestion = MetadataSuggestion(
            entity_type=entity_type, entity_id=entity_id, field_name=field_name,
            current_value=_json_dump(canonical[field_name] if current_value is None else current_value, limit=MAX_VALUE_BYTES),
            suggested_value=_json_dump(suggested_value, limit=MAX_VALUE_BYTES), provider=provider,
            provider_entity_id=provider_entity_id, confidence=confidence, confidence_level=confidence_level,
            match_explanation=match_explanation,
            positive_evidence=_json_dump(positive_evidence, limit=MAX_EVIDENCE_BYTES),
            conflicting_evidence=_json_dump(conflicting_evidence, limit=MAX_EVIDENCE_BYTES),
            status="pending", created_by_job_id=created_by_job_id, reviewed_by=reviewed_by,
            discovery_id=discovery_id, match_result_id=match_result_id,
        )
        db.add(suggestion)
        db.flush()
        return suggestion

    def get_suggestion(self, db: Session, suggestion_id: int) -> MetadataSuggestion:
        item = db.get(MetadataSuggestion, suggestion_id)
        if item is None:
            raise MetadataServiceError("metadata_suggestion_not_found", "Metadata suggestion not found.", 404)
        return item

    def list_suggestions(self, db: Session, *, entity_type: str | None = None,
                         entity_id: int | None = None, provider: str | None = None,
                         status: str | None = None, confidence_level: str | None = None,
                         field_name: str | None = None, created_from: datetime | None = None,
                         created_to: datetime | None = None, offset: int = 0, limit: int = 50) -> tuple[list[MetadataSuggestion], int]:
        if entity_type is not None and entity_type not in ENTITY_TYPES:
            raise MetadataServiceError("metadata_invalid_entity_type", "Unsupported metadata entity type.")
        if status is not None and status not in STATUSES:
            raise MetadataServiceError("metadata_invalid_status", "Unsupported suggestion status.")
        if confidence_level is not None and confidence_level not in CONFIDENCE_LEVELS:
            raise MetadataServiceError("metadata_invalid_confidence_level", "Unsupported confidence level.")
        if field_name is not None:
            self._validate_field(field_name)
        conditions = []
        for column, value in ((MetadataSuggestion.entity_type, entity_type), (MetadataSuggestion.entity_id, entity_id),
                              (MetadataSuggestion.provider, provider), (MetadataSuggestion.status, status),
                              (MetadataSuggestion.confidence_level, confidence_level), (MetadataSuggestion.field_name, field_name)):
            if value is not None:
                conditions.append(column == value)
        if created_from is not None: conditions.append(MetadataSuggestion.created_at >= created_from)
        if created_to is not None: conditions.append(MetadataSuggestion.created_at <= created_to)
        total = db.scalar(select(func.count()).select_from(MetadataSuggestion).where(*conditions)) or 0
        items = list(db.scalars(select(MetadataSuggestion).where(*conditions).order_by(MetadataSuggestion.created_at.desc(), MetadataSuggestion.id.desc()).offset(offset).limit(limit)).all())
        return items, total

    def list_pending_suggestions(self, db: Session, **filters: Any) -> tuple[list[MetadataSuggestion], int]:
        filters["status"] = "pending"
        return self.list_suggestions(db, **filters)

    def accept_suggestion(self, db: Session, suggestion_id: int, *, reviewed_by: str | None = None) -> MetadataSuggestion:
        suggestion = self.get_suggestion(db, suggestion_id)
        if suggestion.status != "pending":
            raise MetadataServiceError("metadata_invalid_transition", "Only pending suggestions can be accepted.", 409)
        now = utcnow_naive()
        db.execute(update(MetadataSuggestion).where(
            MetadataSuggestion.entity_type == suggestion.entity_type,
            MetadataSuggestion.entity_id == suggestion.entity_id,
            MetadataSuggestion.field_name == suggestion.field_name,
            MetadataSuggestion.id != suggestion.id,
            MetadataSuggestion.status.in_(CURRENT_STATUSES),
        ).values(status="superseded", reviewed_at=now))
        suggestion.status = "accepted"
        suggestion.reviewed_at = now
        suggestion.reviewed_by = reviewed_by or suggestion.reviewed_by
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise MetadataServiceError("metadata_acceptance_conflict", "A competing suggestion was accepted concurrently.", 409) from exc
        return suggestion

    def reject_suggestion(self, db: Session, suggestion_id: int, *, reviewed_by: str | None = None) -> MetadataSuggestion:
        suggestion = self.get_suggestion(db, suggestion_id)
        if suggestion.status != "pending":
            raise MetadataServiceError("metadata_invalid_transition", "Only pending suggestions can be rejected.", 409)
        now = utcnow_naive()
        suggestion.status, suggestion.reviewed_at, suggestion.rejected_at = "rejected", now, now
        suggestion.reviewed_by = reviewed_by or suggestion.reviewed_by
        db.flush()
        return suggestion

    def supersede_suggestion(self, db: Session, suggestion_id: int, *, reviewed_by: str | None = None) -> MetadataSuggestion:
        suggestion = self.get_suggestion(db, suggestion_id)
        if suggestion.status not in {"pending", "accepted"}:
            raise MetadataServiceError("metadata_invalid_transition", "Suggestion cannot be superseded from its current status.", 409)
        suggestion.status, suggestion.reviewed_at = "superseded", utcnow_naive()
        suggestion.reviewed_by = reviewed_by or suggestion.reviewed_by
        db.flush()
        return suggestion

    def record_history(self, db: Session, **values: Any) -> MetadataHistory:
        self._validate_entity(values["entity_type"], values["entity_id"], db, require_existing=False)
        self._validate_field(values["field_name"])
        values["previous_value"] = _json_dump(values.get("previous_value"), limit=MAX_VALUE_BYTES)
        values["new_value"] = _json_dump(values.get("new_value"), limit=MAX_VALUE_BYTES)
        history = MetadataHistory(**values)
        db.add(history); db.flush()
        return history

    def get_history(self, db: Session, entity_type: str, entity_id: int, *, offset: int = 0,
                    limit: int = 50) -> tuple[list[MetadataHistory], int]:
        self._validate_entity(entity_type, entity_id, db, require_existing=False)
        conditions = (MetadataHistory.entity_type == entity_type, MetadataHistory.entity_id == entity_id)
        total = db.scalar(select(func.count()).select_from(MetadataHistory).where(*conditions)) or 0
        items = list(db.scalars(select(MetadataHistory).where(*conditions).order_by(
            MetadataHistory.changed_at.desc(), MetadataHistory.id.desc()).offset(offset).limit(limit)).all())
        return items, total

    def compare(self, db: Session, entity_type: str, entity_id: int) -> dict[str, Any]:
        current = self.canonical_metadata(db, entity_type, entity_id)
        suggestions, _ = self.list_suggestions(db, entity_type=entity_type, entity_id=entity_id, limit=1000)
        return {"entity_type": entity_type, "entity_id": entity_id, "current": current,
                "suggestions": [serialize_suggestion(item) for item in suggestions]}

    def review_model(self, db: Session, entity_type: str, entity_id: int) -> dict[str, Any]:
        comparison = self.compare(db, entity_type, entity_id)
        grouped = {field: [] for field in sorted(METADATA_FIELDS)}
        for item in comparison["suggestions"]:
            grouped[item["field_name"]].append(item)
        return {"entity_type": entity_type, "entity_id": entity_id,
                "fields": [{"field_name": field, "current_value": comparison["current"][field], "suggestions": grouped[field]} for field in sorted(grouped)]}


class MetadataApplicationService:
    """The only writer for accepted suggestions; it never touches files or tags."""
    def _normal(self, value: Any) -> Any:
        if isinstance(value, str):
            return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()
        return value

    def _validate(self, field: str, value: Any, canonical: dict[str, Any]) -> str | None:
        if field not in APPLICABLE_FIELDS:
            return "unsupported_metadata_field"
        if value is None: return None
        if field in {"track_number", "total_tracks", "disc_number", "total_discs", "year"}:
            if isinstance(value, bool) or not isinstance(value, int): return "invalid_metadata_value"
            if field == "year" and not 1000 <= value <= utcnow_naive().year + 1: return "invalid_metadata_value"
            if field != "year" and value < 1: return "invalid_metadata_value"
            number = canonical.get("track_number" if field == "total_tracks" else "disc_number")
            if field in {"total_tracks", "total_discs"} and number is not None and value < number: return "invalid_metadata_value"
        elif field in {"release_date", "original_release_date"}:
            if not isinstance(value, str) or not re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", value): return "invalid_metadata_value"
        elif field.startswith("musicbrainz_"):
            if not isinstance(value, str) or len(value) > 255 or not re.fullmatch(r"[0-9a-fA-F-]{8,64}", value): return "invalid_metadata_value"
        elif field == "isrc":
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z]{2}[A-Za-z0-9]{3}\d{7}", value): return "invalid_metadata_value"
        elif not isinstance(value, str) or len(value) > MAX_TEXT_LENGTH:
            return "invalid_metadata_value"
        return None

    def build_preview(self, db: Session, song_id: int, suggestion_ids: list[int] | None = None, *, initiated_by: str | None = None) -> dict[str, Any]:
        song = db.get(Song, song_id)
        if song is None: raise MetadataServiceError("song_not_found", "Song not found.", 404)
        query = select(MetadataSuggestion).where(MetadataSuggestion.entity_type == "song", MetadataSuggestion.entity_id == song_id)
        if suggestion_ids is None: query = query.where(MetadataSuggestion.status == "accepted")
        else: query = query.where(MetadataSuggestion.id.in_(suggestion_ids))
        suggestions = list(db.scalars(query.order_by(MetadataSuggestion.id)).all())
        found = {s.id for s in suggestions}
        if suggestion_ids and found != set(suggestion_ids): raise MetadataServiceError("suggestion_not_found", "One or more suggestions were not found.", 404)
        canonical = metadata_service.canonical_metadata(db, "song", song_id); operations=[]
        for s in suggestions:
            expected, proposed = _json_load(s.current_value), _json_load(s.suggested_value)
            current = canonical[s.field_name]
            validation = self._validate(s.field_name, proposed, canonical)
            if s.status != "accepted": status = "already_applied" if s.status == "applied" else "superseded"
            elif validation == "unsupported_metadata_field": status = "unsupported"
            elif validation: status = "invalid"
            elif self._normal(current) == self._normal(proposed): status = "unchanged"
            elif self._normal(current) != self._normal(expected): status = "stale"
            else: status = "applicable"
            operations.append({"suggestion_id":s.id,"field_name":s.field_name,"current_value":current,"expected_current_value":expected,"proposed_value":proposed,"normalized_equal":self._normal(current)==self._normal(proposed),"status":status,"applicability":status=="applicable","validation_error":validation,"reversible":status=="applicable"})
        return {"target_entity_type":"song", "target_entity_id":song_id, "selected_suggestion_ids":[s.id for s in suggestions], "canonical_snapshot":canonical, "operations":operations, "created_at":utcnow_naive(), "initiated_by":initiated_by}

    def _reserve(self, db: Session, song_ids: list[int], task: Task) -> None:
        # Discovery and application are mutually exclusive per Song, never globally.
        conflict = db.scalar(select(MetadataDiscoveryLock.task_id).where(MetadataDiscoveryLock.song_id.in_(song_ids)))
        if conflict:
            raise MetadataServiceError("application_conflict", f"Song is reserved by metadata discovery job {conflict}.", 409)
        for song_id in song_ids:
            db.add(MetadataApplicationLock(song_id=song_id, task_id=task.id))
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            owner = db.scalar(select(MetadataApplicationLock.task_id).where(MetadataApplicationLock.song_id.in_(song_ids)))
            raise MetadataServiceError("application_conflict", f"Song is reserved by metadata application job {owner}.", 409) from exc

    def submit(self, db: Session, song_ids: list[int], *, suggestion_ids: list[int] | None = None,
               rollback_history_ids: list[int] | None = None, force: bool = False,
               force_confirmation: bool = False, stale_override_reason: str | None = None,
               initiated_by: str | None = None) -> dict[str, Any]:
        if force and not force_confirmation:
            raise MetadataServiceError("force_confirmation_required", "Force application requires explicit confirmation.", 409)
        ids = sorted(set(song_ids))
        if not ids or len(ids) > 500:
            raise MetadataServiceError("metadata_application_scope_invalid", "Select between one and 500 Songs.")
        if len(set(db.scalars(select(Song.id).where(Song.id.in_(ids))).all())) != len(ids):
            raise MetadataServiceError("song_not_found", "One or more Songs were not found.", 404)
        action = "metadata_rollback" if rollback_history_ids else "metadata_application"
        batch = MetadataApplicationBatch(entity_scope="song", status="queued", initiated_by=initiated_by)
        db.add(batch); db.flush()
        payload = {"action": action, "song_ids": ids, "suggestion_ids": suggestion_ids,
                   "history_ids": rollback_history_ids, "force": force,
                   "stale_override_reason": stale_override_reason, "batch_id": batch.id,
                   "counters": {"fields": {key: 0 for key in ("applied", "unchanged", "stale", "invalid", "unsupported", "failed", "forced")},
                                "rollbacks": {"reversed": 0, "conflicts": 0}}}
        task = create_task(db, name="Rollback Library Metadata" if rollback_history_ids else "Apply Library Metadata",
            spotify_url=f"library://metadata/{action}/{batch.id}", task_type=TaskType.LIBRARY_MAINTENANCE,
            total_items=len(ids), operation_payload=json.dumps(payload, separators=(",", ":")),
            initiated_by=initiated_by, resumable=False, commit=False)
        batch.job_id = task.id
        self._reserve(db, ids, task)
        db.commit(); db.refresh(task)
        return {"job_id": task.id, "batch_id": batch.id, "status": task.status,
                "message": "Metadata application queued. Audio-file tags will not be modified."}

    def release_locks(self, db: Session, task_id: int) -> None:
        db.execute(delete(MetadataApplicationLock).where(MetadataApplicationLock.task_id == task_id))

    def _refresh_derived(self, db: Session, song_id: int, job_id: int) -> dict[str, int]:
        library_search.index_song(db, song_id)
        issues = len(metadata_health.analyze_song(db, song_id, job_id))
        song = db.get(Song, song_id)
        # Reconcile only the old/current projections that contain this Song.
        if song and song.album:
            try: metadata_health.analyze_album(db, metadata_health.album_key(song), job_id)
            except LookupError: pass
        if song and song.artist:
            try: metadata_health.analyze_artist(db, metadata_health.artist_key(song.artist), job_id)
            except LookupError: pass
        return {"issues": issues, "search_refreshed": 1}

    def process_task(self, db: Session, task: Task) -> None:
        payload = json.loads(task.operation_payload or "{}")
        batch = db.get(MetadataApplicationBatch, payload["batch_id"])
        if batch is None: raise RuntimeError("Application batch is missing")
        batch.status = "running"; batch.started_at = batch.started_at or utcnow_naive()
        task.status = TaskStatus.RUNNING.value; task.started_at = task.started_at or utcnow_naive(); db.commit()
        try:
            for song_id in payload["song_ids"]:
                db.refresh(task)
                if task.status in (TaskStatus.CANCELLING.value, TaskStatus.CANCELLED.value):
                    task.status = TaskStatus.CANCELLED.value; break
                task.current_item = f"Song {song_id}"
                try:
                    if payload["action"] == "metadata_rollback":
                        history_ids = [x for x in (payload.get("history_ids") or [])
                                       if (history := db.get(MetadataHistory, x)) is not None and history.entity_id == song_id]
                        for history_id in history_ids:
                            result = self.rollback(db, history_id, force=payload["force"], force_confirmation=True, initiated_by=batch.initiated_by, job_id=task.id, batch_id=batch.id)
                            if result["status"] == "rolled_back": payload["counters"]["rollbacks"]["reversed"] += 1
                    else:
                        result = self.apply_selected(db, song_id, payload.get("suggestion_ids"), force=payload["force"], force_confirmation=True, stale_override_reason=payload.get("stale_override_reason"), initiated_by=batch.initiated_by, batch=batch, job_id=task.id)
                        for op in result["operations"]:
                            key = "applied" if op["status"] == "applied" else op["status"]
                            if key in payload["counters"]["fields"]: payload["counters"]["fields"][key] += 1
                    self._refresh_derived(db, song_id, task.id)
                    task.completed_items += 1
                except MetadataServiceError as exc:
                    task.failed_items += 1; batch.failed_fields += 1
                    if payload["action"] == "metadata_rollback" and exc.code == "rollback_conflict":
                        payload["counters"]["rollbacks"]["conflicts"] += 1
                    record_item_failure(db, task, str(song_id), exc.code.upper()[:80], exc.message)
                except Exception:
                    task.failed_items += 1; batch.failed_fields += 1
                    record_item_failure(db, task, str(song_id), "METADATA_APPLICATION_FAILED", "Canonical metadata could not be updated")
                task.operation_payload = json.dumps(payload, separators=(",", ":")); db.commit()
            if task.status == TaskStatus.RUNNING.value:
                task.status = TaskStatus.COMPLETED_WITH_ERRORS.value if task.failed_items or batch.stale_fields or batch.invalid_fields or batch.unsupported_fields else TaskStatus.COMPLETED.value
            if task.status == TaskStatus.CANCELLED.value:
                batch.status = "cancelled"
            elif payload["action"] == "metadata_rollback":
                batch.status = "partially_rolled_back" if task.failed_items or payload["counters"]["rollbacks"]["conflicts"] else "rolled_back"
            else:
                batch.status = task.status
            batch.completed_at = utcnow_naive(); task.completed_at = utcnow_naive(); task.current_item = None; db.commit()
        finally:
            self.release_locks(db, task.id); db.commit()

    def apply_selected(self, db: Session, song_id: int, suggestion_ids: list[int] | None = None, *, force: bool = False, force_confirmation: bool = False, stale_override_reason: str | None = None, initiated_by: str | None = None, atomic: bool = True, batch: MetadataApplicationBatch | None = None, job_id: int | None = None) -> dict[str, Any]:   
        if force and not force_confirmation: raise MetadataServiceError("force_confirmation_required", "Force application requires explicit confirmation.", 409)
        plan=self.build_preview(db,song_id,suggestion_ids,initiated_by=initiated_by)
        if not plan["operations"]: raise MetadataServiceError("no_applicable_suggestions", "No accepted suggestions were selected.",409)
        batch=batch or MetadataApplicationBatch(entity_scope="song",status="running",total_fields=0,initiated_by=initiated_by,started_at=utcnow_naive())
        if batch.id is None: db.add(batch); db.flush()
        batch.total_fields += len(plan["operations"])
        song=db.get(Song,song_id); assert song is not None
        results=[]
        for operation in plan["operations"]:
            status=operation["status"]
            if status == "stale" and force: status="applicable"; operation["forced"]=True
            if status != "applicable":
                if status == "unchanged": batch.unchanged_fields += 1
                elif status == "stale": batch.stale_fields += 1
                elif status == "invalid": batch.invalid_fields += 1
                elif status == "unsupported": batch.unsupported_fields += 1
                results.append(operation); continue
            suggestion=db.get(MetadataSuggestion, operation["suggestion_id"]); assert suggestion is not None
            setattr(song,FIELD_COLUMNS.get(operation["field_name"],operation["field_name"]),operation["proposed_value"])
            metadata_service.record_history(db,entity_type="song",entity_id=song.id,field_name=operation["field_name"],previous_value=operation["current_value"],new_value=operation["proposed_value"],provider=suggestion.provider,provider_entity_id=suggestion.provider_entity_id,confidence=suggestion.confidence,job_id=job_id,change_source="metadata_application",audio_file_modified=False,reversible=True,reversal_of_history_id=None,suggestion_id=suggestion.id,discovery_id=suggestion.discovery_id,match_result_id=suggestion.match_result_id,application_batch_id=batch.id,forced=bool(operation.get("forced")),stale_override_reason=stale_override_reason if operation.get("forced") else None)
            suggestion.status="applied"; suggestion.applied_at=utcnow_naive(); batch.applied_fields += 1
            if operation.get("forced"): batch.forced_fields += 1
            operation["status"]="applied"; results.append(operation)
        if job_id is None:
            batch.status="completed" if not any(x["status"] in {"stale","invalid","unsupported"} for x in results) else "completed_with_errors";batch.completed_at=utcnow_naive()
        db.flush()
        return {"batch_id":batch.id,"status":batch.status,"operations":results,"message":"Library metadata updated. Audio-file tags were not modified."}

    def rollback_preview(self, db: Session, history_id: int) -> dict[str, Any]:
        history=db.get(MetadataHistory,history_id)
        if history is None: raise MetadataServiceError("history_not_found","Metadata history not found.",404)
        if not history.reversible: raise MetadataServiceError("rollback_not_reversible","This metadata change is not reversible.",409)
        song=db.get(Song,history.entity_id)
        if song is None: raise MetadataServiceError("song_not_found","Song not found.",404)
        current=getattr(song,FIELD_COLUMNS.get(history.field_name,history.field_name)); expected=_json_load(history.new_value)
        return {"history_id":history.id,"field_name":history.field_name,"current_value":current,"restore_value":_json_load(history.previous_value),"status":"applicable" if self._normal(current)==self._normal(expected) else "stale","reversible":True}

    def rollback(self, db: Session, history_id: int, *, force: bool=False, force_confirmation: bool=False, initiated_by: str|None=None, job_id: int | None = None, batch_id: int | None = None) -> dict[str, Any]:
        if force and not force_confirmation: raise MetadataServiceError("force_confirmation_required","Force rollback requires explicit confirmation.",409)
        preview=self.rollback_preview(db,history_id)
        if preview["status"] == "stale" and not force: raise MetadataServiceError("rollback_conflict","Canonical metadata has changed since this history entry.",409)
        history=db.get(MetadataHistory,history_id); song=db.get(Song,history.entity_id); assert history and song
        setattr(song,FIELD_COLUMNS.get(history.field_name,history.field_name),preview["restore_value"])
        metadata_service.record_history(db,entity_type="song",entity_id=song.id,field_name=history.field_name,previous_value=preview["current_value"],new_value=preview["restore_value"],provider="rollback",provider_entity_id=None,confidence=None,job_id=job_id,change_source="metadata_rollback",audio_file_modified=False,reversible=True,reversal_of_history_id=history.id,application_batch_id=batch_id,forced=force)
        db.flush(); return {**preview,"status":"rolled_back","message":"Library metadata updated. Audio-file tags were not modified."}


metadata_application_service = MetadataApplicationService()


def serialize_suggestion(item: MetadataSuggestion) -> dict[str, Any]:
    return {column: getattr(item, column) for column in (
        "id", "entity_type", "entity_id", "field_name", "provider", "provider_entity_id",
        "confidence", "confidence_level", "match_explanation", "status", "created_at",
            "reviewed_at", "applied_at", "rejected_at", "created_by_job_id", "reviewed_by"
            , "discovery_id", "match_result_id"
    )} | {"current_value": _json_load(item.current_value), "suggested_value": _json_load(item.suggested_value),
          "positive_evidence": _json_load(item.positive_evidence), "conflicting_evidence": _json_load(item.conflicting_evidence)}


def serialize_history(item: MetadataHistory) -> dict[str, Any]:
    data = {column: getattr(item, column) for column in (
        "id", "entity_type", "entity_id", "field_name", "provider", "provider_entity_id",
        "confidence", "changed_at", "job_id", "change_source", "audio_file_modified",
        "reversible", "reversal_of_history_id", "suggestion_id", "discovery_id", "match_result_id",
        "application_batch_id", "forced", "stale_override_reason"
    )}
    data.update(previous_value=_json_load(item.previous_value), new_value=_json_load(item.new_value))
    return data


metadata_service = MetadataService()
