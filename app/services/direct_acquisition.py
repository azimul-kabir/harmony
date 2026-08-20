"""Low-latency acquisition for tracks whose source metadata is already known."""
from dataclasses import dataclass
import time
from pathlib import Path

from app.core.logging import logger
from app.domain.download_outcome import DownloadCancelled, DownloadFailed
from app.domain.track import Track
from app.downloaders.spotdl import (
    AudioIdentity,
    fallback_candidate_score,
    validate_track_identity,
)
from app.providers.download_source import SourceResult
from app.providers.youtube_music import YouTubeMusicSource


DIRECT_CONFIDENCE_THRESHOLD = 0.82
DIRECT_CANDIDATE_LIMIT = 5


@dataclass(frozen=True, slots=True)
class DirectCandidate:
    result: SourceResult
    score: float


def _candidate_identity(track: Track, result: SourceResult) -> AudioIdentity:
    """Normalize the common ``Artist - Title`` presentation when unambiguous."""
    title = result.title
    artist = result.artist
    if " - " in title:
        prefix, candidate_title = title.split(" - ", 1)
        try:
            validate_track_identity(
                track, AudioIdentity(candidate_title, prefix, result.duration), strict=True
            )
        except DownloadFailed:
            pass
        else:
            title, artist = candidate_title, prefix
    return AudioIdentity(title, artist, result.duration)


def select_candidate(track: Track, results: list[SourceResult]) -> DirectCandidate | None:
    """Select only a candidate that satisfies Harmony's existing strict rules."""
    accepted: list[DirectCandidate] = []
    for result in results:
        identity = _candidate_identity(track, result)
        try:
            validate_track_identity(track, identity, strict=True)
        except DownloadFailed:
            continue
        # Passing strict validation is itself high confidence; the continuous
        # score ranks safe candidates, including allowed album-context titles.
        score = max(0.9, fallback_candidate_score(track, identity))
        if score >= DIRECT_CONFIDENCE_THRESHOLD:
            accepted.append(DirectCandidate(result, score))
    return max(accepted, key=lambda item: item.score, default=None)


class DirectYouTubeAcquirer:
    def __init__(self, source: YouTubeMusicSource | None = None) -> None:
        self.source = source or YouTubeMusicSource()

    @staticmethod
    def _query(track: Track) -> str:
        # A single metadata-rich query avoids recreating SpotDL's serial retry
        # ladder. ISRC remains validation context and SpotDL fallback context.
        return " ".join(filter(None, (track.artist, track.title, track.album, "audio")))

    def download(self, track: Track, output_dir: Path, job_id: int | None = None) -> Path:
        total_started = time.monotonic()
        search_started = time.monotonic()
        try:
            results = self.source.inspect_search(
                self._query(track), limit=DIRECT_CANDIDATE_LIMIT
            )
        except Exception as exc:
            logger.bind(job_id=job_id).warning(
                "Direct candidate search failed job={} error_type={}",
                job_id, type(exc).__name__,
            )
            raise DownloadFailed(
                "provider_error", "Direct candidate search failed.", "download",
                provider="youtube_music", retryable=True,
                technical_detail=type(exc).__name__,
            ) from exc
        search_seconds = time.monotonic() - search_started
        selected = select_candidate(track, results)
        logger.bind(
            job_id=job_id,
            direct_search_seconds=round(search_seconds, 3),
            candidates=len(results),
            selected_video_id=selected.result.item_id if selected else None,
            candidate_score=selected.score if selected else None,
        ).info(
            "Direct candidate search completed job={} direct_search_seconds={} candidates={} "
            "selected_video_id={} candidate_score={}",
            job_id, round(search_seconds, 3), len(results),
            selected.result.item_id if selected else None,
            selected.score if selected else None,
        )
        if selected is None:
            raise DownloadFailed(
                "exact_match_unavailable", "No safe direct candidate was found.",
                "validation", provider="youtube_music", retryable=False,
                technical_detail="direct_confidence_threshold_not_met",
            )
        try:
            output = self.source.download_candidate(
                track, selected.result.item_id, str(output_dir), job_id
            )
        except DownloadCancelled:
            raise
        except Exception as exc:
            raise DownloadFailed(
                "provider_unavailable", "The selected direct candidate could not be downloaded.",
                "download", provider="youtube_music", retryable=True,
                technical_detail=type(exc).__name__,
            ) from exc
        logger.bind(job_id=job_id).info(
            "Direct acquisition completed job={} spotdl_fallback=false total_acquisition_seconds={}",
            job_id, round(time.monotonic() - total_started, 3),
        )
        return output
