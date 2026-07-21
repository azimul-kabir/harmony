"""Stable provider-neutral Metadata Intelligence APIs."""
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.services.metadata_intelligence import metadata_service, serialize_history, serialize_suggestion

router = APIRouter(tags=["metadata"])


class ReviewRequest(BaseModel):
    reviewed_by: str | None = Field(default=None, max_length=120)


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
