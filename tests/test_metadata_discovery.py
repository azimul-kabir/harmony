import json
import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database.models import MetadataDiscovery, MetadataDiscoveryLock, MetadataMatchResult, Song, Task
from app.domain.metadata.provider import CandidatePage, ExternalId, RecordingCandidate
from app.providers.metadata.errors import ProviderError
from app.services.library_health import LibraryMaintenanceWorker
from app.database.session import SessionLocal
from app.services.metadata_discovery import MAX_RETAINED, metadata_discovery_service, song_searches
from app.services.metadata_intelligence import MetadataServiceError
from app.services.task_service import cancel_task, recover_library_jobs
from app.main import app


def add_song(db, index=1, **values):
    defaults=dict(path=f"/music/discovery-{index}.mp3",filename=f"discovery-{index}.mp3",title="Song",artist="Artist",album="Album",isrc="USABC1234567",availability_status="available")
    defaults.update(values);song=Song(**defaults);db.add(song);db.commit();db.refresh(song);return song


def test_search_strategy_is_ordered_and_bounded():
    with SessionLocal() as db:
        song=add_song(db,musicbrainz_recording_id="recording-id",album_artist="Album Artist")
        labels=[x[0] for x in song_searches(song)]
        assert labels[:3]==["existing_provider_id","isrc","exact_title_artist"]
        assert len(labels)<=6 and labels.index("title_artist_album")>labels.index("exact_title_artist")


def test_single_and_batch_submission_persist_discoveries_and_deduplicate_ids():
    with SessionLocal() as db:
        first,second=add_song(db,1),add_song(db,2)
        task=metadata_discovery_service.submit_songs(db,[second.id,first.id,first.id])
        rows=list(db.scalars(select(MetadataDiscovery).where(MetadataDiscovery.job_id==task.id)).all())
        assert task.total_items==2 and len(rows)==2
        assert len(json.loads(task.operation_payload)["song_ids"])==2


def test_overlapping_scope_conflicts_but_unrelated_scope_does_not():
    with SessionLocal() as db:
        first,second=add_song(db,1),add_song(db,2)
        task=metadata_discovery_service.submit_songs(db,[first.id])
        first_id,second_id,task_id=first.id,second.id,task.id
    with SessionLocal() as competing:
        with pytest.raises(MetadataServiceError) as error: metadata_discovery_service.submit_songs(competing,[first_id,second_id])
        assert error.value.code=="discovery_conflict"
    with SessionLocal() as unrelated_session:
        unrelated=metadata_discovery_service.submit_songs(unrelated_session,[second_id])
        assert unrelated.id != task_id


def test_queued_cancellation_releases_song_reservation():
    with SessionLocal() as db:
        song=add_song(db);task=metadata_discovery_service.submit_songs(db,[song.id]);cancel_task(db,task)
        assert db.get(MetadataDiscoveryLock,song.id) is None
        assert metadata_discovery_service.submit_songs(db,[song.id]).status=="queued"


def test_restart_interrupts_discovery_and_releases_lock():
    with SessionLocal() as db:
        song=add_song(db);task=metadata_discovery_service.submit_songs(db,[song.id]);task.status="running";db.commit()
        recover_library_jobs(db);db.refresh(task)
        assert task.status=="interrupted" and db.get(MetadataDiscoveryLock,song.id) is None


def test_missing_song_discovery_record_is_retained():
    with SessionLocal() as db:
        song=add_song(db);task=metadata_discovery_service.submit_songs(db,[song.id]);discovery=db.scalar(select(MetadataDiscovery).where(MetadataDiscovery.job_id==task.id))
        song.availability_status="missing";db.commit()
        assert db.get(MetadataDiscovery,discovery.id) is not None


class FakeProvider:
    def __init__(self, *, fail_first=False, no_results=False): self.calls=[];self.fail_first=fail_first;self.no_results=no_results
    async def lookup(self,*args,**kwargs): return self._candidate()
    async def search(self,entity_type,query,**kwargs):
        self.calls.append(query)
        if self.fail_first and len(self.calls)==1: raise ProviderError("timeout","Provider timed out",provider="musicbrainz",operation="search")
        items=[] if self.no_results else [self._candidate()]
        return CandidatePage(items=items,offset=0,limit=10,total=len(items))
    def _candidate(self):
        return RecordingCandidate(provider="musicbrainz",provider_entity_id="recording",title="Song",artist="Artist",album="Album",
            duration_seconds=180,external_ids=(ExternalId(namespace="isrc",value="USABC1234567"),))


def run_worker(task_id):
    worker=LibraryMaintenanceWorker();worker._loop=asyncio.new_event_loop()
    try:
        with SessionLocal() as db: worker.process_task(db,db.get(Task,task_id))
    finally: worker._loop.close();worker._loop=None


def test_single_song_job_success_and_partial_provider_failure(monkeypatch):
    provider=FakeProvider(fail_first=True)
    monkeypatch.setattr("app.services.metadata_discovery.get_provider",lambda name:provider)
    with SessionLocal() as db: song=add_song(db,duration=180);task=metadata_discovery_service.submit_songs(db,[song.id]);task_id=task.id
    run_worker(task_id)
    with SessionLocal() as db:
        task=db.get(Task,task_id)
        discovery=db.scalar(select(MetadataDiscovery).where(MetadataDiscovery.job_id==task_id))
        assert task.status=="completed_with_errors" and task.completed_items==1
        assert discovery.status=="completed_with_errors" and discovery.results
        assert json.loads(task.operation_payload)["counters"]["provider_failures"]==1


def test_single_song_job_no_match(monkeypatch):
    monkeypatch.setattr("app.services.metadata_discovery.get_provider",lambda name:FakeProvider(no_results=True))
    with SessionLocal() as db: song=add_song(db);task=metadata_discovery_service.submit_songs(db,[song.id]);task_id=task.id
    run_worker(task_id)
    with SessionLocal() as db:
        task=db.get(Task,task_id)
        assert task.status=="completed" and json.loads(task.operation_payload)["counters"]["unmatched"]==1


def test_selected_candidate_generates_all_normalized_supported_fields():
    with SessionLocal() as db:
        song=add_song(db,title=None,artist=None,album=None,isrc=None)
        candidate=RecordingCandidate(provider="musicbrainz",provider_entity_id="recording-id",title="Title",artist="Artist",album_artist="Album Artist",album="Album",
            track_number=2,total_tracks=10,disc_number=1,total_discs=2,release_date="2020-02-03",original_release_date="2019-01-01",year=2020,
            genres=("Rock",),isrc="USABC1234567",release_id="release-id",release_group_id="group-id",artist_id="artist-id",release_artist_id="release-artist-id")
        discovery=MetadataDiscovery(entity_type="song",entity_id=str(song.id),provider="musicbrainz",status="completed",matcher_version="v",scoring_version="v")
        db.add(discovery);db.flush()
        result=MetadataMatchResult(discovery_id=discovery.id,provider_entity_id="recording-id",rank=1,score=90,confidence_level="high",viable=True,ambiguous=False,hard_rejection=False,
            candidate_summary=json.dumps(candidate.model_dump(mode="json")),positive_evidence="[]",conflicting_evidence="[]",unavailable_evidence="[]",rejection_reasons="[]",search_provenance="[]")
        db.add(result);db.flush();discovery.selected_match_result_id=result.id;db.commit()
        generated=metadata_discovery_service.generate_suggestions(db,discovery.id);db.commit()
        fields={x.field_name for x in generated["suggestions"]}
        assert {"title","artist","album_artist","album","track_number","total_tracks","disc_number","total_discs","release_date","original_release_date","year","genre","isrc",
            "musicbrainz_recording_id","musicbrainz_release_id","musicbrainz_release_group_id","musicbrainz_artist_id","musicbrainz_release_artist_id"}==fields
        assert not generated["failures"] and all(x.status=="pending" and x.discovery_id==discovery.id and x.match_result_id==result.id for x in generated["suggestions"])


def test_start_poll_cancel_api_and_structured_conflict():
    with SessionLocal() as db: song=add_song(db);song_id=song.id
    client=TestClient(app)
    started=client.post(f"/api/metadata/discoveries/songs/{song_id}",json={"provider":"musicbrainz"})
    assert started.status_code==200
    payload=started.json();assert payload["job"]["status"]=="queued" and payload["discovery"]["job_id"]==payload["job"]["id"]
    polled=client.get(f"/api/tasks/jobs/{payload['job']['id']}")
    assert polled.status_code==200 and polled.json()["operation"]=="metadata_discovery"
    conflict=client.post(f"/api/metadata/discoveries/songs/{song_id}",json={"provider":"musicbrainz"})
    assert conflict.status_code==409 and conflict.json()["error"]["code"]=="discovery_conflict"
    cancelled=client.post(f"/api/tasks/jobs/{payload['job']['id']}/cancel")
    assert cancelled.status_code==200 and cancelled.json()["status"]=="cancelled"
