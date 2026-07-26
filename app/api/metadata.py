"""Stable provider-neutral Metadata Intelligence APIs."""
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.database.models import MetadataApplicationBatch, MetadataHistory, Song
from app.services.file_tag_writer import preview as tag_preview, write_song

from app.database.session import get_db
from app.services.metadata_intelligence import APPLICABLE_FIELDS, MANUAL_EDIT_FIELDS, metadata_service, metadata_application_service, serialize_history, serialize_suggestion

router = APIRouter(tags=["metadata"])


class ReviewRequest(BaseModel):
    reviewed_by: str | None = Field(default=None, max_length=120)


class ApplicationRequest(BaseModel):
    suggestion_ids: list[int] | None = None
    force: bool = False
    force_confirmation: bool = False
    stale_override_reason: str | None = Field(default=None, max_length=500)
    initiated_by: str | None = Field(default=None, max_length=120)
    atomic: bool = True


class TagWriteRequest(BaseModel):
    song_ids: list[int] = Field(min_length=1, max_length=5000)
    embed_artwork: bool = True


class TagWriteOptions(BaseModel):
    embed_artwork: bool = True


class ManualMetadataRequest(BaseModel):
    changes: dict[str, Any] = Field(min_length=1, max_length=len(MANUAL_EDIT_FIELDS))
    initiated_by: str | None = Field(default=None, max_length=120)


def _page(items: list[Any], total: int, limit: int, offset: int) -> dict[str, Any]:
    return {"items": [serialize_suggestion(item) for item in items], "pagination": {
        "total": total, "limit": limit, "offset": offset, "has_more": offset + len(items) < total,
    }}


@router.get("/api/library/songs/{song_id}/metadata", summary="Compare canonical and proposed Song metadata")
def get_song_metadata(song_id: int, db: Session = Depends(get_db)):
    return metadata_service.review_model(db, "song", song_id)


@router.post("/api/library/songs/{song_id}/metadata/manual-preview", summary="Validate and preview manual canonical metadata edits")
def preview_manual_metadata(song_id: int, request: ManualMetadataRequest, db: Session = Depends(get_db)):
    return metadata_application_service.preview_manual(
        db, song_id, request.changes, initiated_by=request.initiated_by
    )


@router.post("/api/library/songs/{song_id}/metadata/manual-apply", summary="Queue audited manual canonical metadata edits")
def apply_manual_metadata(song_id: int, request: ManualMetadataRequest, db: Session = Depends(get_db)):
    return metadata_application_service.submit_manual(
        db, song_id, request.changes, initiated_by=request.initiated_by
    )


@router.get("/api/library/songs/{song_id}/metadata/suggestions", summary="List Song metadata suggestions")
def get_song_suggestions(song_id: int, status: str | None = None,
                         limit: int = Query(default=50, ge=1, le=200),
                         offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
    metadata_service.canonical_metadata(db, "song", song_id)
    items, total = metadata_service.list_suggestions(db, entity_type="song", entity_id=song_id,
                                                      status=status, limit=limit, offset=offset)
    return _page(items, total, limit, offset)


@router.get("/api/library/songs/{song_id}/metadata/history", summary="List Song metadata history")
def get_song_history(song_id: int, limit: int = Query(default=50, ge=1, le=200),
                     offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
    metadata_service.canonical_metadata(db, "song", song_id)
    items, total = metadata_service.get_history(db, "song", song_id, limit=limit, offset=offset)
    return {"items": [serialize_history(item) for item in items], "pagination": {
        "total": total, "limit": limit, "offset": offset, "has_more": offset + len(items) < total,
    }}


@router.get("/api/library/songs/{song_id}/metadata/application-preview")
def preview_accepted_application(song_id: int, db: Session = Depends(get_db)):
    return metadata_application_service.build_preview(db, song_id)


@router.post("/api/library/songs/{song_id}/metadata/application-preview")
def preview_selected_application(song_id: int, request: ApplicationRequest, db: Session = Depends(get_db)):
    return metadata_application_service.build_preview(db, song_id, request.suggestion_ids, initiated_by=request.initiated_by)


@router.get("/api/library/songs/{song_id}/metadata/tag-preview", summary="Preview canonical tags before modifying an audio file")
def preview_file_tags(song_id: int, db: Session = Depends(get_db)):
    song = db.get(Song, song_id)
    if song is None:
        from app.services.metadata_intelligence import MetadataServiceError
        raise MetadataServiceError("metadata_song_not_found", "Song not found.", 404)
    return tag_preview(song)


@router.post("/api/library/songs/{song_id}/metadata/write-tags", summary="Explicitly write canonical metadata to one audio file")
def write_file_tags(song_id: int, request: TagWriteOptions | None = None, db: Session = Depends(get_db)):
    song = db.get(Song, song_id)
    if song is None:
        from app.services.metadata_intelligence import MetadataServiceError
        raise MetadataServiceError("metadata_song_not_found", "Song not found.", 404)
    return write_song(db, song, embed_artwork=True if request is None else request.embed_artwork)


@router.post("/api/library/metadata/write-tags", summary="Explicitly write canonical metadata for selected audio files")
def write_selected_file_tags(request: TagWriteRequest, db: Session = Depends(get_db)):
    totals = {key: 0 for key in ("succeeded", "skipped", "unsupported", "missing", "failed", "artwork_embedded", "artwork_unchanged", "artwork_unavailable", "artwork_unsupported", "artwork_failed")}
    for song_id in dict.fromkeys(request.song_ids):
        song = db.get(Song, song_id)
        if song is None:
            totals["missing"] += 1
            continue
        result = write_song(db, song, embed_artwork=request.embed_artwork)
        status = result["status"]
        if status == "succeeded": totals["succeeded"] += 1
        elif status == "unsupported" or result.get("reason") == "unsupported": totals["unsupported"] += 1
        elif result.get("reason") == "missing_or_unsafe": totals["missing"] += 1
        elif status == "skipped": totals["skipped"] += 1
        else: totals["failed"] += 1
        if status == "succeeded":
            artwork = result.get("artwork", "unchanged")
            if artwork == "embedded": totals["artwork_embedded"] += 1
            elif artwork == "unavailable": totals["artwork_unavailable"] += 1
            elif artwork == "unsupported": totals["artwork_unsupported"] += 1
            else: totals["artwork_unchanged"] += 1
        elif result.get("reason") == "Artwork verification failed.": totals["artwork_failed"] += 1
    return {"totals": totals}


@router.post("/api/library/songs/{song_id}/metadata/apply")
def apply_accepted_application(song_id: int, request: ApplicationRequest, db: Session = Depends(get_db)):
    return metadata_application_service.submit(db, [song_id], force=request.force, force_confirmation=request.force_confirmation, stale_override_reason=request.stale_override_reason, initiated_by=request.initiated_by)


@router.post("/api/library/songs/{song_id}/metadata/apply-selected")
def apply_selected_application(song_id: int, request: ApplicationRequest, db: Session = Depends(get_db)):
    return metadata_application_service.submit(db, [song_id], suggestion_ids=request.suggestion_ids, force=request.force, force_confirmation=request.force_confirmation, stale_override_reason=request.stale_override_reason, initiated_by=request.initiated_by)


@router.get("/api/metadata/history/{history_id}/rollback-preview")
def preview_rollback(history_id: int, db: Session = Depends(get_db)):
    return metadata_application_service.rollback_preview(db, history_id)


@router.post("/api/metadata/history/{history_id}/rollback")
def rollback(history_id: int, request: ApplicationRequest, db: Session = Depends(get_db)):
    history = db.get(MetadataHistory, history_id)
    if history is None: from app.services.metadata_intelligence import MetadataServiceError; raise MetadataServiceError("history_not_found", "Metadata history not found.", 404)
    return metadata_application_service.submit(db, [history.entity_id], rollback_history_ids=[history_id], force=request.force, force_confirmation=request.force_confirmation, initiated_by=request.initiated_by)


@router.post("/api/metadata/applications/apply")
def apply_selected_songs(song_ids: list[int], request: ApplicationRequest, db: Session = Depends(get_db)):
    """Queue accepted metadata for an explicit selected-Song scope."""
    return metadata_application_service.submit(db, song_ids, suggestion_ids=request.suggestion_ids, force=request.force,
        force_confirmation=request.force_confirmation, stale_override_reason=request.stale_override_reason, initiated_by=request.initiated_by)


@router.get("/api/metadata/batches")
def list_batches(status: str | None = None, job_id: int | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    conditions = [MetadataApplicationBatch.status == status] if status else []
    if job_id is not None: conditions.append(MetadataApplicationBatch.job_id == job_id)
    total = db.scalar(select(func.count()).select_from(MetadataApplicationBatch).where(*conditions)) or 0
    items = db.scalars(select(MetadataApplicationBatch).where(*conditions).order_by(MetadataApplicationBatch.created_at.desc(), MetadataApplicationBatch.id.desc()).offset(offset).limit(limit)).all()
    return {"items": [_serialize_batch(x) for x in items], "pagination": {"total": total, "limit": limit, "offset": offset, "has_more": offset + len(items) < total}}


@router.get("/api/metadata/batches/{batch_id}")
def get_batch(batch_id: int, db: Session = Depends(get_db)):
    batch = db.get(MetadataApplicationBatch, batch_id)
    if batch is None: from app.services.metadata_intelligence import MetadataServiceError; raise MetadataServiceError("batch_not_found", "Metadata application batch not found.", 404)
    return _serialize_batch(batch)


@router.get("/api/metadata/batches/{batch_id}/results")
def batch_results(batch_id: int, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    get_batch(batch_id, db)
    rows = db.scalars(select(MetadataHistory).where(MetadataHistory.application_batch_id == batch_id).order_by(MetadataHistory.id).offset(offset).limit(limit)).all()
    total = db.scalar(select(func.count()).select_from(MetadataHistory).where(MetadataHistory.application_batch_id == batch_id)) or 0
    return {"items": [serialize_history(x) for x in rows], "pagination": {"total": total, "limit": limit, "offset": offset, "has_more": offset + len(rows) < total}}


@router.post("/api/metadata/batches/{batch_id}/rollback")
def rollback_batch(batch_id: int, request: ApplicationRequest, db: Session = Depends(get_db)):
    get_batch(batch_id, db)
    rows = db.scalars(select(MetadataHistory).where(MetadataHistory.application_batch_id == batch_id, MetadataHistory.reversible.is_(True))).all()
    if not rows: from app.services.metadata_intelligence import MetadataServiceError; raise MetadataServiceError("rollback_not_available", "No reversible batch history is available.", 409)
    return metadata_application_service.submit(db, sorted({x.entity_id for x in rows}), rollback_history_ids=[x.id for x in rows], force=request.force, force_confirmation=request.force_confirmation, initiated_by=request.initiated_by)


@router.get("/api/metadata/history")
def history(song_id: int | None = None, field_name: str | None = None, provider: str | None = None, job_id: int | None = None, batch_id: int | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    conditions = []
    for column, value in ((MetadataHistory.entity_id, song_id), (MetadataHistory.field_name, field_name), (MetadataHistory.provider, provider), (MetadataHistory.job_id, job_id), (MetadataHistory.application_batch_id, batch_id)):
        if value is not None: conditions.append(column == value)
    total = db.scalar(select(func.count()).select_from(MetadataHistory).where(*conditions)) or 0
    rows = db.scalars(select(MetadataHistory).where(*conditions).order_by(MetadataHistory.changed_at.desc(), MetadataHistory.id.desc()).offset(offset).limit(limit)).all()
    return {"items": [serialize_history(x) for x in rows], "pagination": {"total": total, "limit": limit, "offset": offset, "has_more": offset + len(rows) < total}}


@router.get("/api/metadata/history/{history_id}")
def history_item(history_id: int, db: Session = Depends(get_db)):
    row = db.get(MetadataHistory, history_id)
    if row is None: from app.services.metadata_intelligence import MetadataServiceError; raise MetadataServiceError("history_not_found", "Metadata history not found.", 404)
    return serialize_history(row)


def _serialize_batch(item: MetadataApplicationBatch) -> dict[str, Any]:
    return {key: getattr(item, key) for key in ("id", "entity_scope", "status", "total_fields", "applied_fields", "unchanged_fields", "stale_fields", "invalid_fields", "unsupported_fields", "failed_fields", "forced_fields", "initiated_by", "created_at", "started_at", "completed_at", "job_id")}


@router.get("/api/metadata/application/capabilities")
def application_capabilities():
    return {"entity_types": ["song"], "supported_fields": sorted(APPLICABLE_FIELDS), "manual_edit_fields": sorted(MANUAL_EDIT_FIELDS), "unsupported_fields": ["artwork_source"], "limits": {"max_text_length": 500, "year_min": 1000}}


@router.get("/api/metadata/suggestions/pending", summary="List pending metadata suggestions")
def pending_suggestions(
    provider: str | None = None, status: str = "pending", confidence_level: str | None = None,
    entity_type: str | None = None, field_name: str | None = None,
    song_id: int | None = Query(default=None, ge=1), album_id: int | None = Query(default=None, ge=1),
    artist_id: int | None = Query(default=None, ge=1), created_from: datetime | None = None,
    created_to: datetime | None = None, limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0), db: Session = Depends(get_db),
):
    ids = [("song", song_id), ("album", album_id), ("artist", artist_id)]
    selected = [(kind, value) for kind, value in ids if value is not None]
    if len(selected) > 1:
        from app.services.metadata_intelligence import MetadataServiceError
        raise MetadataServiceError("metadata_ambiguous_entity_filter", "Specify only one song, album, or artist ID filter.")
    entity_id = None
    if selected:
        selected_type, entity_id = selected[0]
        if entity_type is not None and entity_type != selected_type:
            from app.services.metadata_intelligence import MetadataServiceError
            raise MetadataServiceError("metadata_ambiguous_entity_filter", "Entity type conflicts with the supplied entity ID filter.")
        entity_type = selected_type
    items, total = metadata_service.list_suggestions(
        db, provider=provider, confidence_level=confidence_level, entity_type=entity_type,
        entity_id=entity_id, field_name=field_name, created_from=created_from,
        created_to=created_to, status=status, limit=limit, offset=offset,
    )
    return _page(items, total, limit, offset)


@router.get("/api/metadata/suggestions/{suggestion_id}", summary="Get metadata suggestion details")
def suggestion_details(suggestion_id: int, db: Session = Depends(get_db)):
    return serialize_suggestion(metadata_service.get_suggestion(db, suggestion_id))


@router.post("/api/metadata/suggestions/{suggestion_id}/accept", summary="Accept a suggestion without applying it")
def accept_suggestion(suggestion_id: int, request: ReviewRequest, db: Session = Depends(get_db)):
    item = metadata_service.accept_suggestion(db, suggestion_id, reviewed_by=request.reviewed_by)
    db.commit(); db.refresh(item)
    return serialize_suggestion(item)


@router.post("/api/metadata/suggestions/{suggestion_id}/reject", summary="Reject and retain a suggestion")
def reject_suggestion(suggestion_id: int, request: ReviewRequest, db: Session = Depends(get_db)):
    item = metadata_service.reject_suggestion(db, suggestion_id, reviewed_by=request.reviewed_by)
    db.commit(); db.refresh(item)
    return serialize_suggestion(item)
