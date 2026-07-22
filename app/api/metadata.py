"""Stable provider-neutral Metadata Intelligence APIs."""
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.services.metadata_intelligence import APPLICABLE_FIELDS, metadata_service, metadata_application_service, serialize_history, serialize_suggestion

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


def _page(items: list[Any], total: int, limit: int, offset: int) -> dict[str, Any]:
    return {"items": [serialize_suggestion(item) for item in items], "pagination": {
        "total": total, "limit": limit, "offset": offset, "has_more": offset + len(items) < total,
    }}


@router.get("/api/library/songs/{song_id}/metadata", summary="Compare canonical and proposed Song metadata")
def get_song_metadata(song_id: int, db: Session = Depends(get_db)):
    return metadata_service.review_model(db, "song", song_id)


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


@router.post("/api/library/songs/{song_id}/metadata/apply")
def apply_accepted_application(song_id: int, request: ApplicationRequest, db: Session = Depends(get_db)):
    result = metadata_application_service.apply_selected(db, song_id, None, force=request.force, force_confirmation=request.force_confirmation, stale_override_reason=request.stale_override_reason, initiated_by=request.initiated_by, atomic=request.atomic)
    db.commit()
    return result


@router.post("/api/library/songs/{song_id}/metadata/apply-selected")
def apply_selected_application(song_id: int, request: ApplicationRequest, db: Session = Depends(get_db)):
    result = metadata_application_service.apply_selected(db, song_id, request.suggestion_ids, force=request.force, force_confirmation=request.force_confirmation, stale_override_reason=request.stale_override_reason, initiated_by=request.initiated_by, atomic=request.atomic)
    db.commit()
    return result


@router.get("/api/metadata/history/{history_id}/rollback-preview")
def preview_rollback(history_id: int, db: Session = Depends(get_db)):
    return metadata_application_service.rollback_preview(db, history_id)


@router.post("/api/metadata/history/{history_id}/rollback")
def rollback(history_id: int, request: ApplicationRequest, db: Session = Depends(get_db)):
    result = metadata_application_service.rollback(db, history_id, force=request.force, force_confirmation=request.force_confirmation, initiated_by=request.initiated_by)
    db.commit()
    return result


@router.get("/api/metadata/application/capabilities")
def application_capabilities():
    return {"entity_types": ["song"], "supported_fields": sorted(APPLICABLE_FIELDS), "unsupported_fields": ["artwork_source"], "limits": {"max_text_length": 500, "year_min": 1000}}


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
