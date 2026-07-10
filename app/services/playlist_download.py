from sqlalchemy.orm import Session

from app.domain.download_summary import PlaylistDownloadSummary
from app.domain.queue import QueueStatus
from app.domain.track_download_result import (
    TrackDownloadResult,
    TrackDownloadStatus,
)
from app.exceptions.download import TrackAlreadyExistsError
from app.services.download_queue import enqueue_track
from app.services.playlist import import_playlist


def download_playlist(
    db: Session,
    url: str,
) -> PlaylistDownloadSummary:
    playlist = import_playlist(url)

    owned = 0
    queued = 0
    already_queued = 0

    track_results: list[TrackDownloadResult] = []

    for track in playlist.tracks:
        try:
            result = enqueue_track(
                db=db,
                track=track,
            )

            if result.status == QueueStatus.CREATED:
                queued += 1

                track_results.append(
                    TrackDownloadResult(
                        title=track.title,
                        artist=track.artist,
                        status=TrackDownloadStatus.QUEUED,
                        job_id=result.job_id,
                    )
                )

            else:
                already_queued += 1

                track_results.append(
                    TrackDownloadResult(
                        title=track.title,
                        artist=track.artist,
                        status=TrackDownloadStatus.ALREADY_QUEUED,
                        job_id=result.job_id,
                    )
                )

        except TrackAlreadyExistsError:
            owned += 1

            track_results.append(
                TrackDownloadResult(
                    title=track.title,
                    artist=track.artist,
                    status=TrackDownloadStatus.OWNED,
                )
            )

    return PlaylistDownloadSummary(
        playlist_name=playlist.name,
        total=playlist.track_count,
        owned=owned,
        already_queued=already_queued,
        queued=queued,
        failed=0,
        tracks=track_results,
    )
