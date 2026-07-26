"""Stable provider-neutral metadata discovery APIs."""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.services.metadata_discovery import metadata_discovery_service, serialize_discovery, serialize_result
from app.services.metadata_intelligence import serialize_suggestion
from app.services.metadata_matching import MATCHER_VERSION, SCORING_VERSION, VERSION_MARKERS, metadata_matcher
from app.services.metadata_discovery import canonical_snapshot
from app.services.task_progress import serialize_task_progress
from app.database.models import Song

router=APIRouter(prefix="/api/metadata/discoveries",tags=["metadata-discovery"])


class DiscoverRequest(BaseModel):
    provider: str="musicbrainz"


class SelectionRequest(BaseModel):
    result_id: int
    confirm_ambiguous: bool=False
    confirm_low_confidence: bool=False


class BatchRequest(DiscoverRequest):
    song_ids: list[int] = Field(min_length=1, max_length=500)
    initiated_by: str|None=None


class HealthDiscoveryRequest(DiscoverRequest):
    rule_ids: list[str] = Field(min_length=1, max_length=50)
    maximum: int|None=None
    initiated_by: str|None=None


class HealthIssueDiscoveryRequest(DiscoverRequest):
    issue_ids:list[int] = Field(min_length=1, max_length=500)
    initiated_by:str|None=None


@router.post("/songs/{song_id}")
async def discover_song(song_id:int, body:DiscoverRequest, db:Session=Depends(get_db)):
    task=metadata_discovery_service.submit_songs(db,[song_id],provider_name=body.provider,scope="song")
    discovery=metadata_discovery_service.list(db,job_id=task.id,limit=1)[0][0]
    return {"job":serialize_task_progress(task),"discovery":serialize_discovery(discovery)}


@router.post("/songs")
def discover_selected_songs(body:BatchRequest,db:Session=Depends(get_db)):
    task=metadata_discovery_service.submit_songs(db,body.song_ids,provider_name=body.provider,initiated_by=body.initiated_by)
    return {"job":serialize_task_progress(task),"discovery_ids":[x.id for x in metadata_discovery_service.list(db,job_id=task.id,limit=200)[0]]}


@router.post("/health-rules")
def discover_health_rules(body:HealthDiscoveryRequest,db:Session=Depends(get_db)):
    task=metadata_discovery_service.submit_health_rules(db,body.rule_ids,provider_name=body.provider,maximum=body.maximum,initiated_by=body.initiated_by)
    return {"job":serialize_task_progress(task),"discovery_ids":[x.id for x in metadata_discovery_service.list(db,job_id=task.id,limit=200)[0]]}


@router.post("/health-issues")
def discover_health_issues(body:HealthIssueDiscoveryRequest,db:Session=Depends(get_db)):
    task=metadata_discovery_service.submit_health_issues(db,body.issue_ids,provider_name=body.provider,initiated_by=body.initiated_by)
    return {"job":serialize_task_progress(task),"discovery_ids":[x.id for x in metadata_discovery_service.list(db,job_id=task.id,limit=200)[0]]}


@router.get("")
def list_discoveries(provider:str|None=None,entity_type:str|None=None,entity_id:str|None=None,status:str|None=None,
    confidence:str|None=None,ambiguous:bool|None=None,selected:bool|None=None,min_score:float|None=Query(default=None,ge=0,le=100),
    max_score:float|None=Query(default=None,ge=0,le=100),job_id:int|None=None,created_from:datetime|None=None,
    created_to:datetime|None=None,limit:int=Query(default=50,ge=1,le=200),offset:int=Query(default=0,ge=0),db:Session=Depends(get_db)):
    items,total=metadata_discovery_service.list(db,provider=provider,entity_type=entity_type,entity_id=entity_id,status=status,
        confidence=confidence,ambiguous=ambiguous,selected=selected,min_score=min_score,max_score=max_score,job_id=job_id,
        created_from=created_from,created_to=created_to,limit=limit,offset=offset)
    return {"items":[serialize_discovery(x) for x in items],"pagination":{"total":total,"limit":limit,"offset":offset,"has_more":offset+len(items)<total}}


@router.get("/capabilities")
def capabilities():
    return {"matcher_version":MATCHER_VERSION,"scoring_version":SCORING_VERSION,"entity_types":["song","album","artist"],
        "public_entity_types":["song"],"internal_scoring_entity_types":["song","album","artist"],
        "thresholds":metadata_matcher.config.__dict__,"version_markers":sorted(VERSION_MARKERS),
        "limits":{"search_variants":6,"results_per_search":10,"total_candidates":40,"retained_candidates":15}}


@router.get("/{discovery_id}")
def discovery_details(discovery_id:int,db:Session=Depends(get_db)):
    item=metadata_discovery_service.get(db,discovery_id);data=serialize_discovery(item,details=True)
    if item.entity_type=="song":
        song=db.get(Song,int(item.entity_id));data["stale"]=song is None or canonical_snapshot(song)!=item.canonical_snapshot_hash
    return data


@router.post("/{discovery_id}/rerun")
async def rerun(discovery_id:int,body:DiscoverRequest,db:Session=Depends(get_db)):
    old=metadata_discovery_service.get(db,discovery_id)
    if old.entity_type!="song":
        from app.services.metadata_intelligence import MetadataServiceError
        raise MetadataServiceError("unsupported_entity_type","Rerun is currently supported for songs only.",400)
    task=metadata_discovery_service.submit_songs(db,[int(old.entity_id)],provider_name=body.provider or old.provider,scope="rerun")
    item=metadata_discovery_service.list(db,job_id=task.id,limit=1)[0][0]
    return {"job":serialize_task_progress(task),"discovery":serialize_discovery(item)}


@router.post("/{discovery_id}/select")
def select_candidate(discovery_id:int,body:SelectionRequest,db:Session=Depends(get_db)):
    item=metadata_discovery_service.select(db,discovery_id,body.result_id,confirm_ambiguous=body.confirm_ambiguous,confirm_low=body.confirm_low_confidence)
    db.commit(); return serialize_discovery(metadata_discovery_service.get(db,item.id),details=True)


@router.delete("/{discovery_id}/selection")
def clear_candidate(discovery_id:int,db:Session=Depends(get_db)):
    item=metadata_discovery_service.clear_selection(db,discovery_id);db.commit();return serialize_discovery(item,details=True)


@router.post("/{discovery_id}/suggestions")
def generate_suggestions(discovery_id:int,db:Session=Depends(get_db)):
    result=metadata_discovery_service.generate_suggestions(db,discovery_id);db.commit();return {"items":[serialize_suggestion(x) for x in result["suggestions"]],"failures":result["failures"]}


@router.get("/{discovery_id}/compare")
def compare(discovery_id:int,left_result_id:int,right_result_id:int,db:Session=Depends(get_db)):
    item=metadata_discovery_service.get(db,discovery_id); by_id={x.id:x for x in item.results}
    if left_result_id not in by_id or right_result_id not in by_id:
        from app.services.metadata_intelligence import MetadataServiceError
        raise MetadataServiceError("result_not_found","One or both match results were not found.",404)
    return {"left":serialize_result(by_id[left_result_id]),"right":serialize_result(by_id[right_result_id]),
        "score_difference":round(by_id[left_result_id].score-by_id[right_result_id].score,2)}
