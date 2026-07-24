"""Deterministic provider-neutral metadata matching and ranking."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from typing import Any, Iterable

from app.core.time import utcnow_naive
from app.database.models import Song
from app.domain.metadata.matching import (AlbumMatchInput, ArtistMatchInput, MatchEvidence,
    MatchResult, SongMatchInput)
from app.domain.metadata.provider import ArtistCandidate, RecordingCandidate, ReleaseCandidate

MATCHER_VERSION = "provider-neutral-v1"
SCORING_VERSION = "deterministic-2026-07"
VERSION_MARKERS = frozenset({"live", "remix", "remaster", "remastered", "acoustic", "instrumental",
    "karaoke", "demo", "edit", "radio edit", "extended", "mono", "stereo", "cover", "anniversary", "deluxe"})


@dataclass(frozen=True)
class ScoringConfig:
    exact_threshold: float = 97
    high_threshold: float = 88
    medium_threshold: float = 72
    low_threshold: float = 50
    ambiguity_margin: float = 3
    duration_close_seconds: float = 3
    duration_near_seconds: float = 10
    duration_implausible_seconds: float = 90


def normalize_text(value: str | None) -> str:
    if not value: return ""
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.translate(str.maketrans({"’":"'", "‘":"'", "–":"-", "—":"-", "‐":"-", "／":"/"}))
    return " ".join(re.sub(r"[^\w\s'&+/-]", " ", value).split())


def similarity(left: str | None, right: str | None) -> float:
    a, b = normalize_text(left), normalize_text(right)
    return SequenceMatcher(None, a, b).ratio() if a and b else 0


def _markers(*values: str | None) -> set[str]:
    text = " ".join(normalize_text(v) for v in values if v)
    found={marker for marker in VERSION_MARKERS if re.search(rf"\b{re.escape(marker)}\b", text)}
    if "remastered" in found: found.discard("remastered");found.add("remaster")
    if "radio edit" in found: found.discard("edit")
    return found


def _year(value: str | None) -> int | None:
    match = re.match(r"^(\d{4})", value or "")
    return int(match.group(1)) if match else None


def song_input(song: Song) -> SongMatchInput:
    ids = {}
    if song.musicbrainz_recording_id: ids["musicbrainz"] = song.musicbrainz_recording_id
    return SongMatchInput(song_id=song.id, title=song.title, artist=song.artist, album_artist=song.album_artist,
        album=song.album, duration_seconds=song.duration, track_number=song.track, total_tracks=song.track_total,
        disc_number=song.disc, total_discs=song.disc_total, year=song.year, isrc=song.isrc,
        existing_provider_ids=ids, compilation=song.compilation, filename=song.filename,
        file_path=song.path, codec=song.codec, bitrate=song.bitrate)


class MetadataMatcher:
    def __init__(self, config: ScoringConfig | None = None): self.config = config or ScoringConfig()

    def _level(self, score: float, hard: bool, exact_identity: bool, contradiction: bool) -> str:
        if hard or score < self.config.low_threshold: return "rejected"
        if score >= self.config.exact_threshold and exact_identity and not contradiction: return "exact"
        if score >= self.config.high_threshold: return "high"
        if score >= self.config.medium_threshold: return "medium"
        return "low"

    def score_song(self, local: SongMatchInput, candidate: RecordingCandidate,
                   provenance: Iterable[str] = ()) -> MatchResult:
        pos, conflict, missing, reasons = [], [], [], []
        score, available = 0.0, 0.0
        def evidence(field: str, weight: float, ratio: float | None, lv: Any, cv: Any, *, penalty: float = 0) -> None:
            nonlocal score, available
            if lv is None or lv == "" or cv is None or cv == "":
                missing.append(MatchEvidence(kind="unavailable", field=field, message=f"{field} unavailable", local_value=lv, candidate_value=cv)); return
            available += weight
            points = weight * max(0, min(1, ratio or 0))
            score += points
            target = pos if (ratio or 0) >= .75 else conflict
            target.append(MatchEvidence(kind="positive" if target is pos else "conflict", field=field,
                message=f"{field} {'agrees' if target is pos else 'differs'}", points=round(points if target is pos else -penalty, 2), local_value=lv, candidate_value=cv))
            if target is conflict: score -= penalty

        candidate_isrcs={normalize_text(x.value) for x in candidate.external_ids if x.namespace.casefold()=="isrc"}
        if candidate.isrc: candidate_isrcs.add(normalize_text(candidate.isrc))
        exact_identity = False
        hard = False
        if local.isrc and candidate_isrcs:
            available += 36
            if normalize_text(local.isrc) in candidate_isrcs:
                score += 36; exact_identity = True; pos.append(MatchEvidence(kind="positive", field="isrc", message="ISRC exact match", points=36))
            else:
                hard = True; reasons.append("conflicting_isrc"); conflict.append(MatchEvidence(kind="conflict", field="isrc", message="ISRC conflicts", points=-36, local_value=local.isrc, candidate_value=sorted(candidate_isrcs)))
        else: missing.append(MatchEvidence(kind="unavailable", field="isrc", message="ISRC comparison unavailable"))
        known = local.existing_provider_ids.get(candidate.provider)
        if known:
            available += 40
            if known == candidate.provider_entity_id:
                score += 40; exact_identity = True; pos.append(MatchEvidence(kind="positive", field="provider_id", message="Existing provider recording ID exact match", points=40))
            else:
                hard = True; reasons.append("conflicting_existing_provider_id"); conflict.append(MatchEvidence(kind="conflict", field="provider_id", message="Existing provider ID conflicts", points=-40))
        else: missing.append(MatchEvidence(kind="unavailable", field="provider_id", message="Existing provider ID unavailable"))
        title_ratio = max([similarity(local.title, candidate.title), *(similarity(local.title, alias) for alias in candidate.aliases)])
        evidence("title", 26, title_ratio, local.title, candidate.title, penalty=18 if title_ratio < .35 else 4)
        artist_ratio = similarity(local.artist, candidate.artist)
        evidence("artist_credit", 22, artist_ratio, local.artist, candidate.artist, penalty=24 if artist_ratio < .3 else 4)
        evidence("album", 6, similarity(local.album, candidate.album), local.album, candidate.album, penalty=3)
        evidence("album_artist", 4, similarity(local.album_artist, candidate.album_artist), local.album_artist, candidate.album_artist, penalty=2)
        if local.duration_seconds is not None and candidate.duration_seconds is not None:
            available += 8; delta = abs(local.duration_seconds-candidate.duration_seconds)
            ratio = 1 if delta <= self.config.duration_close_seconds else .5 if delta <= self.config.duration_near_seconds else 0
            if delta > self.config.duration_implausible_seconds:
                hard=True; reasons.append("implausible_duration_difference"); score -= 12
                conflict.append(MatchEvidence(kind="conflict", field="duration", message="Duration difference is implausible", points=-12, local_value=local.duration_seconds, candidate_value=candidate.duration_seconds))
            elif ratio: score += 8*ratio; pos.append(MatchEvidence(kind="positive", field="duration", message=f"Duration differs by {delta:.1f}s", points=8*ratio))
            else: score -= 3; conflict.append(MatchEvidence(kind="conflict", field="duration", message=f"Duration differs by {delta:.1f}s", points=-3))
        else: missing.append(MatchEvidence(kind="unavailable", field="duration", message="Duration comparison unavailable"))
        evidence("track_number", 3, 1 if local.track_number == candidate.track_number else 0, local.track_number, candidate.track_number, penalty=1)
        evidence("disc_number", 2, 1 if local.disc_number == candidate.disc_number else 0, local.disc_number, candidate.disc_number, penalty=1)
        cy = _year(candidate.release_date)
        evidence("release_year", 3, 1 if local.year == cy else .5 if local.year and cy and abs(local.year-cy) <= 1 else 0, local.year, cy, penalty=1)
        local_markers, candidate_markers = _markers(local.title, local.album), _markers(candidate.title, candidate.album, candidate.release_group,
            candidate.recording_disambiguation,candidate.release_disambiguation)
        incompatible = local_markers ^ candidate_markers
        if incompatible:
            hard=True; reasons.append("incompatible_version_markers"); score -= 30
            conflict.append(MatchEvidence(kind="conflict", field="version", message="Identity-significant version markers differ", points=-30,
                local_value=sorted(local_markers), candidate_value=sorted(candidate_markers)))
        elif local_markers:
            score += 4; available += 4; pos.append(MatchEvidence(kind="positive", field="version", message="Version markers agree", points=4, local_value=sorted(local_markers)))
        if local.compilation is not None and candidate.compilation is not None:
            available+=2
            if local.compilation==candidate.compilation: score+=2;pos.append(MatchEvidence(kind="positive",field="compilation",message="Compilation context agrees",points=2))
            else: score-=1;conflict.append(MatchEvidence(kind="conflict",field="compilation",message="Compilation context differs",points=-1))
        else: missing.append(MatchEvidence(kind="unavailable",field="compilation",message="Compilation comparison unavailable"))
        raw = max(0, min(100, (score / available * 100) if available else 0))
        if title_ratio < .2: hard=True; reasons.append("severe_title_contradiction")
        if artist_ratio < .2 and local.artist and candidate.artist: hard=True; reasons.append("severe_artist_contradiction")
        level = self._level(raw, hard, exact_identity, bool(conflict))
        summary = candidate.model_dump(mode="json", exclude={"relationships"})
        return MatchResult(provider=candidate.provider, entity_type="song", local_entity_id=str(local.song_id),
            provider_entity_id=candidate.provider_entity_id, candidate_summary=summary, score=round(raw, 2),
            confidence_level=level, viable=not hard and raw >= self.config.low_threshold, hard_rejection=hard,
            positive_evidence=tuple(pos), conflicting_evidence=tuple(conflict), unavailable_evidence=tuple(missing),
            rejection_reasons=tuple(dict.fromkeys(reasons)), search_provenance=tuple(sorted(set(provenance))),
            scoring_version=SCORING_VERSION, matcher_version=MATCHER_VERSION, created_at=utcnow_naive())

    def score_album(self, local: AlbumMatchInput, candidate: ReleaseCandidate) -> MatchResult:
        title, artist = similarity(local.title, candidate.title), similarity(local.album_artist, candidate.artist)
        score = round(70*title + 30*artist, 2); hard = title < .25 or artist < .2
        level = self._level(score, hard, local.existing_provider_ids.get(candidate.provider)==candidate.provider_entity_id, hard)
        return MatchResult(provider=candidate.provider, entity_type="album", local_entity_id=local.album_key,
            provider_entity_id=candidate.provider_entity_id, candidate_summary=candidate.model_dump(mode="json"), score=score,
            confidence_level=level, viable=not hard and score >= self.config.low_threshold, hard_rejection=hard,
            rejection_reasons=("severe_title_contradiction",) if hard else (), scoring_version=SCORING_VERSION,
            matcher_version=MATCHER_VERSION, created_at=utcnow_naive())

    def score_artist(self, local: ArtistMatchInput, candidate: ArtistCandidate) -> MatchResult:
        ratios = [similarity(local.name, candidate.title)] + [similarity(x, candidate.title) for x in local.aliases]
        score=round(max(ratios)*100,2); hard=score < 25
        level=self._level(score, hard, local.existing_provider_ids.get(candidate.provider)==candidate.provider_entity_id, hard)
        return MatchResult(provider=candidate.provider, entity_type="artist", local_entity_id=local.artist_key,
            provider_entity_id=candidate.provider_entity_id, candidate_summary=candidate.model_dump(mode="json"), score=score,
            confidence_level=level, viable=not hard and score >= self.config.low_threshold, hard_rejection=hard,
            rejection_reasons=("severe_artist_contradiction",) if hard else (), scoring_version=SCORING_VERSION,
            matcher_version=MATCHER_VERSION, created_at=utcnow_naive())

    def rank(self, results: Iterable[MatchResult]) -> list[MatchResult]:
        ranked=sorted(results, key=lambda x: (-x.score, x.provider, x.provider_entity_id))
        viable=[x for x in ranked if x.viable]
        ambiguous_ids=set()
        if len(viable)>1 and viable[0].score-viable[1].score <= self.config.ambiguity_margin:
            ambiguous_ids.update((viable[0].provider_entity_id, viable[1].provider_entity_id))
        output=[]
        for rank, item in enumerate(ranked,1):
            ambiguous=item.provider_entity_id in ambiguous_ids
            level="high" if ambiguous and item.confidence_level=="exact" else item.confidence_level
            output.append(item.model_copy(update={"rank":rank,"ambiguous":ambiguous,"confidence_level":level}))
        return output


metadata_matcher = MetadataMatcher()
