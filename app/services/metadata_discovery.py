"""Candidate retrieval, durable discovery review, selection, and suggestion projection."""
from __future__ import annotations

import asyncio
import hashlib
import json
import unicodedata
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.time import utcnow_naive
from app.core.config import get_settings
from app.database.models import MetadataDiscovery, MetadataDiscoveryLock, MetadataIssue, MetadataMatchResult, MetadataSuggestion, Song, Task
from app.domain.task import TaskStatus, TaskType
from app.domain.metadata.provider import RecordingCandidate
from app.providers.metadata.errors import ProviderError
from app.providers.metadata.registry import get_provider
from app.services.metadata_intelligence import MetadataServiceError, metadata_service
from app.services.metadata_matching import MATCHER_VERSION, SCORING_VERSION, ScoringConfig, metadata_matcher, song_input
from app.services.task_service import create_task

MAX_SEARCH_VARIANTS = 6
RESULTS_PER_SEARCH = 10
MAX_CANDIDATES = 40
MAX_RETAINED = 15
MAX_JSON_BYTES = 8192
SUPPORTED_HEALTH_RULES = frozenset({
    "missing_musicbrainz_recording_id", "missing_musicbrainz_release_id", "missing_musicbrainz_artist_id",
    "missing_title", "placeholder_title", "filename_derived_title", "missing_artist", "placeholder_artist",
    "missing_album", "placeholder_album", "suspicious_whitespace", "inconsistent_capitalization",
})


def _dump(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(text.encode()) > MAX_JSON_BYTES: raise MetadataServiceError("discovery_payload_too_large", "Bounded discovery data was exceeded.", 413)
    return text


def _load(value: str | None) -> Any: return json.loads(value) if value else None


def canonical_snapshot(song: Song) -> str:
    values=(song.title,song.artist,song.album_artist,song.album,song.duration,song.track,song.track_total,
        song.disc,song.disc_total,song.year,song.isrc,song.musicbrainz_recording_id,song.musicbrainz_release_id,
        song.musicbrainz_artist_id,song.compilation,song.metadata_hash)
    return hashlib.sha256(_dump(values).encode()).hexdigest()


def _quote(value: str) -> str: return '"' + value.replace('"', "")[:200] + '"'


def _health_normalize(value:str|None, *, artist:bool=False) -> str:
    result=" ".join(unicodedata.normalize("NFKC",str(value or "")).strip().casefold().split())
    if artist and result.startswith("the "): result=result[4:]
    return result


def _issue_song_ids(db:Session,issues:list[MetadataIssue],maximum:int|None=None) -> list[int]:
    ids={int(x.song_id) for x in issues if x.song_id is not None}
    album_keys={x.album_key for x in issues if x.album_key};artist_keys={x.artist_key for x in issues if x.artist_key}
    if album_keys or artist_keys:
        rows=db.execute(select(Song.id,Song.artist,Song.album_artist,Song.album).where(Song.availability_status=="available").execution_options(yield_per=250))
        for song_id,artist,album_artist,album in rows:
            album_key=f"{_health_normalize(album_artist or artist,artist=True)}::{_health_normalize(album)}"
            if album_key in album_keys or _health_normalize(artist,artist=True) in artist_keys: ids.add(song_id)
            if maximum is not None and len(ids)>=maximum: break
    return sorted(ids)[:maximum]


def song_searches(song: Song) -> list[tuple[str, str, str | None]]:
    """Ordered bounded searches: (label, operation, query/id)."""
    searches=[]
    if song.musicbrainz_recording_id: searches.append(("existing_provider_id", "lookup", song.musicbrainz_recording_id))
    if song.isrc: searches.append(("isrc", "search", f'isrc:{_quote(song.isrc)}'))
    if song.title and song.artist:
        searches.append(("exact_title_artist", "search", f'recording:{_quote(song.title)} AND artist:{_quote(song.artist)}'))
        if song.album: searches.append(("title_artist_album", "search", f'recording:{_quote(song.title)} AND artist:{_quote(song.artist)} AND release:{_quote(song.album)}'))
    if song.title and song.album_artist: searches.append(("title_album_artist", "search", f'recording:{_quote(song.title)} AND artist:{_quote(song.album_artist)}'))
    if song.title and song.artist: searches.append(("normalized_title_artist", "search", f'{song.title[:200]} {song.artist[:200]}'))
    return searches[:MAX_SEARCH_VARIANTS]


class MetadataDiscoveryService:
    def _reserve(self, db: Session, song_ids: list[int], task: Task) -> None:
        for song_id in song_ids: db.add(MetadataDiscoveryLock(song_id=song_id,task_id=task.id))
        try: db.flush()
        except IntegrityError as exc:
            db.rollback()
            active=db.scalar(select(MetadataDiscoveryLock).where(MetadataDiscoveryLock.song_id.in_(song_ids)))
            detail=f" Active job {active.task_id}." if active else ""
            raise MetadataServiceError("discovery_conflict",f"One or more Songs already have active metadata discovery.{detail}",409) from exc

    def submit_songs(self, db: Session, song_ids: list[int], *, provider_name: str="musicbrainz",
                     initiated_by: str|None=None, scope: str="selected") -> Task:
        ids=sorted(set(song_ids))
        settings=get_settings()
        if not ids: raise MetadataServiceError("entity_not_found","At least one Song ID is required.",400)
        if len(ids)>settings.metadata_discovery_max_batch_songs: raise MetadataServiceError("discovery_scope_too_large","Selected discovery scope exceeds the configured limit.",413)
        existing=set(db.scalars(select(Song.id).where(Song.id.in_(ids))).all())
        if not existing: raise MetadataServiceError("entity_not_found","No selected Songs were found.",404)
        payload={"action":"metadata_discovery","scope":scope,"provider":provider_name,"song_ids":ids,
            "counters":{"matched":0,"ambiguous":0,"unmatched":0,"provider_failures":0,"candidates_found":0,
                "candidates_deduplicated":0,"viable_candidates":0,"rejected_candidates":0}}
        digest=hashlib.sha256(",".join(map(str,ids)).encode()).hexdigest()[:20]
        task=create_task(db,name="Discover Metadata Match" if len(ids)==1 else f"Discover Metadata Matches ({len(ids)} Songs)",
            spotify_url=f"library://metadata-discovery/{scope}/{digest}",task_type=TaskType.LIBRARY_MAINTENANCE,
            total_items=len(ids),operation_payload=_dump(payload),resource_key=None,initiated_by=initiated_by,resumable=False,commit=False)
        self._reserve(db,ids,task)
        for song_id in ids:
            db.add(MetadataDiscovery(entity_type="song",entity_id=str(song_id),provider=provider_name,status="queued",job_id=task.id,
                matcher_version=MATCHER_VERSION,scoring_version=SCORING_VERSION,query_summary=_dump({"scope":scope}),
                canonical_snapshot_hash=canonical_snapshot(db.get(Song,song_id)) if song_id in existing else None))
        db.commit();db.refresh(task);return task

    def submit_health_rules(self, db:Session, rule_ids:list[str], *, provider_name:str="musicbrainz", maximum:int|None=None,
                            initiated_by:str|None=None) -> Task:
        rules=sorted(set(rule_ids))
        if not rules or any(rule not in SUPPORTED_HEALTH_RULES for rule in rules):
            raise MetadataServiceError("unsupported_health_rule","One or more health rules do not support discovery.",400)
        issues=list(db.scalars(select(MetadataIssue).where(MetadataIssue.status=="open",MetadataIssue.rule_id.in_(rules)).order_by(MetadataIssue.id)).all())
        ids=_issue_song_ids(db,issues,maximum)
        return self.submit_songs(db,ids,provider_name=provider_name,initiated_by=initiated_by,scope="health_rules")

    def submit_health_issues(self, db:Session, issue_ids:list[int], *, provider_name:str="musicbrainz", initiated_by:str|None=None) -> Task:
        issues=list(db.scalars(select(MetadataIssue).where(MetadataIssue.id.in_(sorted(set(issue_ids)))),).all())
        if not issues or any(x.rule_id not in SUPPORTED_HEALTH_RULES for x in issues):
            raise MetadataServiceError("unsupported_health_rule","Selected health issues do not support Song discovery.",400)
        return self.submit_songs(db,_issue_song_ids(db,issues),provider_name=provider_name,initiated_by=initiated_by,scope="health_issues")

    async def discover_song(self, db: Session, song_id: int, *, provider_name: str = "musicbrainz",
                            cancel_event: asyncio.Event | None = None, job_id: int | None = None,
                            discovery_id: int | None = None, progress=None) -> MetadataDiscovery:
        song=db.get(Song, song_id)
        if song is None: raise MetadataServiceError("entity_not_found", "Song not found.", 404)
        try: provider=get_provider(provider_name)
        except KeyError as exc: raise MetadataServiceError("provider_unavailable", "Metadata provider is unavailable.", 503) from exc
        searches=song_searches(song); local=song_input(song)
        discovery=db.get(MetadataDiscovery,discovery_id) if discovery_id else None
        if discovery is None:
            discovery=MetadataDiscovery(entity_type="song", entity_id=str(song_id), provider=provider_name, status="running",
                job_id=job_id, matcher_version=MATCHER_VERSION, scoring_version=SCORING_VERSION,
                canonical_snapshot_hash=canonical_snapshot(song))
            db.add(discovery)
        discovery.query_summary=_dump({"searches":[x[0] for x in searches]}); db.commit(); db.refresh(discovery)
        discovery.status="running";db.commit()
        candidates: dict[tuple[str,str], RecordingCandidate] = {}; provenance: dict[tuple[str,str],set[str]]={}; failures=[];raw_candidates=duplicates=0
        for index,(label, operation, query) in enumerate(searches,1):
            if cancel_event and cancel_event.is_set():
                discovery.status="cancelled"; discovery.completed_at=utcnow_naive(); db.flush(); return discovery
            try:
                if operation=="lookup":
                    item=await provider.lookup("recording", query or "", cancel_event=cancel_event); items=[item]
                else:
                    page=await provider.search("recording", query or "", limit=RESULTS_PER_SEARCH, cancel_event=cancel_event); items=page.items
                for item in items:
                    if not isinstance(item, RecordingCandidate): continue
                    raw_candidates+=1
                    key=(item.provider,item.provider_entity_id)
                    if key in candidates: duplicates+=1
                    candidates.setdefault(key,item); provenance.setdefault(key,set()).add(label)
                    if len(candidates)>=MAX_CANDIDATES: break
            except ProviderError as exc:
                if exc.code=="cancelled": discovery.status="cancelled"; discovery.completed_at=utcnow_naive(); db.flush(); return discovery
                failures.append({"search":label,"code":exc.code[:80],"message":exc.message[:300]})
            if progress: progress(index,len(searches),raw_candidates,duplicates,len(failures))
        results=metadata_matcher.rank(metadata_matcher.score_song(local, item, provenance[key]) for key,item in candidates.items())[:MAX_RETAINED]
        for result in results:
            db.add(MetadataMatchResult(discovery_id=discovery.id, provider_entity_id=result.provider_entity_id,
                rank=result.rank, score=result.score, confidence_level=result.confidence_level, viable=result.viable,
                ambiguous=result.ambiguous, hard_rejection=result.hard_rejection,
                candidate_summary=_dump(result.candidate_summary), positive_evidence=_dump([x.model_dump(mode="json") for x in result.positive_evidence]),
                conflicting_evidence=_dump([x.model_dump(mode="json") for x in result.conflicting_evidence]),
                unavailable_evidence=_dump([x.model_dump(mode="json") for x in result.unavailable_evidence]),
                rejection_reasons=_dump(result.rejection_reasons), search_provenance=_dump(result.search_provenance)))
        discovery.ambiguous=any(x.ambiguous for x in results); discovery.completed_at=utcnow_naive()
        discovery.status="completed_with_errors" if failures else "completed"; discovery.error_metadata=_dump(failures) if failures else None
        db.flush(); return discovery

    def release_locks(self, db:Session, task_id:int) -> None:
        db.execute(delete(MetadataDiscoveryLock).where(MetadataDiscoveryLock.task_id==task_id))

    def get(self, db: Session, discovery_id: int) -> MetadataDiscovery:
        item=db.scalar(select(MetadataDiscovery).options(selectinload(MetadataDiscovery.results)).where(MetadataDiscovery.id==discovery_id))
        if item is None: raise MetadataServiceError("discovery_not_found", "Metadata discovery not found.", 404)
        return item

    def list(self, db: Session, *, provider: str|None=None, entity_type: str|None=None, entity_id: str|None=None,
             status: str|None=None, confidence: str|None=None, ambiguous: bool|None=None, selected: bool|None=None,
             min_score: float|None=None, max_score: float|None=None, job_id: int|None=None,
             created_from: datetime|None=None, created_to: datetime|None=None, offset: int=0, limit: int=50):
        conditions=[]
        for col,val in ((MetadataDiscovery.provider,provider),(MetadataDiscovery.entity_type,entity_type),(MetadataDiscovery.entity_id,entity_id),(MetadataDiscovery.status,status),(MetadataDiscovery.ambiguous,ambiguous),(MetadataDiscovery.job_id,job_id)):
            if val is not None: conditions.append(col==val)
        if selected is not None: conditions.append(MetadataDiscovery.selected_match_result_id.is_not(None) if selected else MetadataDiscovery.selected_match_result_id.is_(None))
        if created_from: conditions.append(MetadataDiscovery.created_at>=created_from)
        if created_to: conditions.append(MetadataDiscovery.created_at<=created_to)
        if confidence or min_score is not None or max_score is not None:
            sub=select(MetadataMatchResult.discovery_id)
            if confidence: sub=sub.where(MetadataMatchResult.confidence_level==confidence)
            if min_score is not None: sub=sub.where(MetadataMatchResult.score>=min_score)
            if max_score is not None: sub=sub.where(MetadataMatchResult.score<=max_score)
            conditions.append(MetadataDiscovery.id.in_(sub))
        total=db.scalar(select(func.count()).select_from(MetadataDiscovery).where(*conditions)) or 0
        items=list(db.scalars(select(MetadataDiscovery).where(*conditions).order_by(MetadataDiscovery.created_at.desc(),MetadataDiscovery.id.desc()).offset(offset).limit(limit)).all())
        return items,total

    def select(self, db: Session, discovery_id: int, result_id: int, *, confirm_ambiguous: bool=False, confirm_low: bool=False) -> MetadataDiscovery:
        discovery=self.get(db, discovery_id); result=next((x for x in discovery.results if x.id==result_id),None)
        if result is None: raise MetadataServiceError("invalid_candidate_selection", "Candidate does not belong to this discovery.", 409)
        if result.hard_rejection or not result.viable: raise MetadataServiceError("rejected_candidate_selection", "Rejected candidates cannot be selected.", 409)
        if result.ambiguous and not confirm_ambiguous: raise MetadataServiceError("ambiguous_selection_requires_confirmation", "Confirm selection of this ambiguous candidate.", 409)
        if result.confidence_level=="low" and not confirm_low: raise MetadataServiceError("ambiguous_selection_requires_confirmation", "Confirm selection of this low-confidence candidate.", 409)
        discovery.selected_match_result_id=result.id; db.flush(); return discovery

    def clear_selection(self, db: Session, discovery_id: int) -> MetadataDiscovery:
        item=self.get(db,discovery_id); item.selected_match_result_id=None; db.flush(); return item

    def generate_suggestions(self, db: Session, discovery_id: int) -> dict[str,Any]:
        discovery=self.get(db,discovery_id)
        if discovery.selected_match_result_id is None: raise MetadataServiceError("no_selected_candidate", "Select a candidate first.", 409)
        result=next(x for x in discovery.results if x.id==discovery.selected_match_result_id)
        if not result.viable or result.hard_rejection: raise MetadataServiceError("rejected_candidate_selection", "Rejected candidates cannot generate suggestions.", 409)
        candidate=_load(result.candidate_summary); song=db.get(Song,int(discovery.entity_id))
        if song is None: raise MetadataServiceError("entity_not_found", "Song not found.", 404)
        values={"title":candidate.get("title"),"artist":candidate.get("artist"),"album":candidate.get("album"),
            "album_artist":candidate.get("album_artist"),"track_number":candidate.get("track_number"),
            "total_tracks":candidate.get("total_tracks"),"disc_number":candidate.get("disc_number"),"total_discs":candidate.get("total_discs"),
            "release_date":candidate.get("release_date"),"original_release_date":candidate.get("original_release_date"),
            "year":candidate.get("year"),"genre":candidate.get("genres",[None])[0] if candidate.get("genres") else None,
            "isrc":candidate.get("isrc"),"musicbrainz_recording_id":candidate.get("provider_entity_id") if discovery.provider=="musicbrainz" else None,
            "musicbrainz_release_id":candidate.get("release_id") if discovery.provider=="musicbrainz" else None,
            "musicbrainz_release_group_id":candidate.get("release_group_id") if discovery.provider=="musicbrainz" else None,
            "musicbrainz_artist_id":candidate.get("artist_id") if discovery.provider=="musicbrainz" else None,
            "musicbrainz_release_artist_id":candidate.get("release_artist_id") if discovery.provider=="musicbrainz" else None}
        canonical=metadata_service.canonical_metadata(db,"song",song.id); created=[]
        failures=[]
        positive=_load(result.positive_evidence); conflicting=_load(result.conflicting_evidence)
        for field,value in values.items():
            if value is None or str(value).strip().casefold()==str(canonical.get(field) or "").strip().casefold(): continue
            encoded=json.dumps(value,ensure_ascii=False,separators=(",",":"))
            duplicate=db.scalar(select(MetadataSuggestion.id).where(MetadataSuggestion.entity_type=="song",MetadataSuggestion.entity_id==song.id,
                MetadataSuggestion.field_name==field,MetadataSuggestion.provider==discovery.provider,MetadataSuggestion.provider_entity_id==result.provider_entity_id,
                MetadataSuggestion.suggested_value==encoded,MetadataSuggestion.status=="pending"))
            if duplicate: continue
            try:
                created.append(metadata_service.create_suggestion(db,entity_type="song",entity_id=song.id,field_name=field,suggested_value=value,
                    provider=discovery.provider,provider_entity_id=result.provider_entity_id,confidence=result.score/100,
                    confidence_level=result.confidence_level,match_explanation=f"Selected {result.confidence_level}-confidence match (score {result.score:.2f}); release context: {candidate.get('release_context') or 'unavailable'}.",
                    positive_evidence=positive,conflicting_evidence=conflicting,created_by_job_id=discovery.job_id,
                    discovery_id=discovery.id,match_result_id=result.id))
            except MetadataServiceError as exc:
                failures.append({"field_name":field,"code":exc.code,"message":exc.message})
        if not created and not failures: raise MetadataServiceError("no_applicable_suggestions", "The selected candidate has no new supported field values.", 409)
        return {"suggestions":created,"failures":failures}


def serialize_result(item: MetadataMatchResult) -> dict[str,Any]:
    return {"id":item.id,"provider_entity_id":item.provider_entity_id,"rank":item.rank,"score":item.score,
        "confidence_level":item.confidence_level,"viable":item.viable,"ambiguous":item.ambiguous,"hard_rejection":item.hard_rejection,
        "candidate_summary":_load(item.candidate_summary),"positive_evidence":_load(item.positive_evidence),
        "conflicting_evidence":_load(item.conflicting_evidence),"unavailable_evidence":_load(item.unavailable_evidence),
        "rejection_reasons":_load(item.rejection_reasons),"search_provenance":_load(item.search_provenance),"created_at":item.created_at}


def serialize_discovery(item: MetadataDiscovery, *, details: bool=False) -> dict[str,Any]:
    data={"id":item.id,"entity_type":item.entity_type,"entity_id":item.entity_id,"provider":item.provider,"status":item.status,
        "selected_match_result_id":item.selected_match_result_id,"ambiguous":item.ambiguous,"created_at":item.created_at,
        "completed_at":item.completed_at,"job_id":item.job_id,"matcher_version":item.matcher_version,"scoring_version":item.scoring_version,
        "query_summary":_load(item.query_summary),"errors":_load(item.error_metadata),"stale":False}
    if item.entity_type=="song":
        # The caller's session is unavailable here; detailed APIs set this field.
        data["canonical_snapshot_hash"]=item.canonical_snapshot_hash
    if details: data["results"]=[serialize_result(x) for x in sorted(item.results,key=lambda x:x.rank)]
    return data


metadata_discovery_service=MetadataDiscoveryService()
