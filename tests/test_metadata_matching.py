from app.domain.metadata.matching import SongMatchInput
from app.domain.metadata.provider import ExternalId, RecordingCandidate
import pytest

from app.services.metadata_matching import MetadataMatcher, ScoringConfig, normalize_text


def candidate(**values):
    base={"provider":"musicbrainz","provider_entity_id":"b","title":"Song","artist":"Artist","duration_seconds":180}
    base.update(values); return RecordingCandidate(**base)


def test_exact_isrc_match_is_strong_and_explainable():
    local=SongMatchInput(song_id=1,title="Song",artist="Artist",duration_seconds=180,isrc="USABC1234567")
    result=MetadataMatcher().score_song(local,candidate(external_ids=(ExternalId(namespace="isrc",value="USABC1234567"),)))
    assert result.score >= 97
    assert result.confidence_level == "exact"
    assert any(x.field=="isrc" for x in result.positive_evidence)


def test_conflicting_isrc_is_hard_rejection():
    local=SongMatchInput(song_id=1,title="Song",artist="Artist",isrc="USABC1234567")
    result=MetadataMatcher().score_song(local,candidate(external_ids=(ExternalId(namespace="isrc",value="GBABC1234567"),)))
    assert result.hard_rejection
    assert "conflicting_isrc" in result.rejection_reasons


def test_version_marker_contradiction_rejects_live_as_studio():
    result=MetadataMatcher().score_song(SongMatchInput(song_id=1,title="Song",artist="Artist"),candidate(title="Song (Live)"))
    assert result.hard_rejection
    assert "incompatible_version_markers" in result.rejection_reasons


def test_missing_fields_are_neutral_and_ties_are_deterministic():
    matcher=MetadataMatcher(); local=SongMatchInput(song_id=1,title="Song",artist="Artist")
    ranked=matcher.rank([matcher.score_song(local,candidate(provider_entity_id="z")),matcher.score_song(local,candidate(provider_entity_id="a"))])
    assert [x.provider_entity_id for x in ranked]==["a","z"]
    assert ranked[0].score==ranked[1].score and ranked[0].ambiguous


def test_existing_provider_id_match_and_conflict():
    matcher=MetadataMatcher()
    exact=matcher.score_song(SongMatchInput(song_id=1,title="Song",artist="Artist",existing_provider_ids={"musicbrainz":"b"}),candidate())
    conflict=matcher.score_song(SongMatchInput(song_id=1,title="Song",artist="Artist",existing_provider_ids={"musicbrainz":"other"}),candidate())
    assert exact.confidence_level=="exact"
    assert conflict.hard_rejection and "conflicting_existing_provider_id" in conflict.rejection_reasons


def test_punctuation_unicode_and_candidate_aliases_are_compared():
    matcher=MetadataMatcher()
    local=SongMatchInput(song_id=1,title="Beyoncé – Halo!",artist="Artist")
    result=matcher.score_song(local,candidate(title="unrelated",aliases=("Beyoncé - Halo",)))
    assert result.viable
    assert normalize_text("ＡＢＣ") == "abc"


def test_album_mismatch_is_limited_and_track_disc_year_are_contextual():
    local=SongMatchInput(song_id=1,title="Song",artist="Artist",album="Original",track_number=2,disc_number=1,year=2020)
    result=MetadataMatcher().score_song(local,candidate(album="Compilation",track_number=3,disc_number=2,release_date="2021-01-01"))
    assert result.viable and not result.hard_rejection
    assert {x.field for x in result.conflicting_evidence} >= {"album","track_number","disc_number"}


@pytest.mark.parametrize("delta,minimum",[(3,85),(10,70),(11,50)])
def test_duration_tolerance_boundaries(delta,minimum):
    result=MetadataMatcher().score_song(SongMatchInput(song_id=1,title="Song",artist="Artist",duration_seconds=180),candidate(duration_seconds=180+delta))
    assert result.score>=minimum


def test_severe_duration_mismatch_rejects():
    result=MetadataMatcher().score_song(SongMatchInput(song_id=1,title="Song",artist="Artist",duration_seconds=180),candidate(duration_seconds=400))
    assert result.hard_rejection and "implausible_duration_difference" in result.rejection_reasons


@pytest.mark.parametrize("marker",["live","remix","acoustic","instrumental","karaoke","demo","edit","radio edit","extended","mono","stereo","cover","anniversary","deluxe"])
def test_identity_markers_reject_version_mismatch(marker):
    result=MetadataMatcher().score_song(SongMatchInput(song_id=1,title="Song",artist="Artist"),candidate(title=f"Song ({marker})"))
    assert result.hard_rejection and "incompatible_version_markers" in result.rejection_reasons


def test_remaster_and_remastered_are_equivalent_markers():
    result=MetadataMatcher().score_song(SongMatchInput(song_id=1,title="Song (Remaster)",artist="Artist"),candidate(title="Song (Remastered)"))
    assert "incompatible_version_markers" not in result.rejection_reasons


def test_exact_requires_identity_not_fuzzy_text_only():
    result=MetadataMatcher().score_song(SongMatchInput(song_id=1,title="Song",artist="Artist",duration_seconds=180),candidate())
    assert result.score==100 and result.confidence_level=="high"


def test_ambiguity_margin_is_configurable():
    matcher=MetadataMatcher(ScoringConfig(ambiguity_margin=0))
    local=SongMatchInput(song_id=1,title="Song",artist="Artist")
    ranked=matcher.rank([matcher.score_song(local,candidate(provider_entity_id="a")),matcher.score_song(local,candidate(provider_entity_id="b",title="Songs"))])
    assert not any(x.ambiguous for x in ranked)
