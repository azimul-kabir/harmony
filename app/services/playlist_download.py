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
from app.services.playlist_manager import export_m3u, save_database_playlist
from app.services.spotify.url import spotify_resource


def download_resolved_playlist(
    db: Session,
    playlist,
    *,
    source_provider: str,
    source_id: str,
) -> PlaylistDownloadSummary:
    db_playlist = save_database_playlist(
        db,
        source_id,
        playlist,
        source_provider=source_provider,
    )
    export_m3u(db, db_playlist, domain_tracks=playlist.tracks)

    owned = 0
    queued = 0
    already_queued = 0
    track_results: list[TrackDownloadResult] = []

    for position, track in enumerate(playlist.tracks, 1):
        try:
            result = enqueue_track(
                db=db,
                track=track,
                queue_position=position,
            )

            if result.status == QueueStatus.CREATED:
                queued += 1
                status = TrackDownloadStatus.QUEUED
            else:
                already_queued += 1
                status = TrackDownloadStatus.ALREADY_QUEUED
            track_results.append(
                TrackDownloadResult(
                    title=track.title,
                    artist=track.artist,
                    status=status,
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
        total=len(playlist.tracks),
        owned=owned,
        already_queued=already_queued,
        queued=queued,
        failed=0,
        tracks=track_results,
    )


def download_playlist(
    db: Session,
    url: str,
) -> PlaylistDownloadSummary:
    playlist = import_playlist(url)
    resource, spotify_id = spotify_resource(url)
    if resource != "playlist":
        raise ValueError("Only Spotify playlists can be downloaded as playlists.")

    return download_resolved_playlist(
        db,
        playlist,
        source_provider="spotify",
        source_id=spotify_id,
    )
