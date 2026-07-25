from sqlalchemy.orm import Session

from app.domain.download_summary import PlaylistDownloadSummary
from app.domain.queue import QueueStatus
from app.domain.track_download_result import (
    TrackDownloadResult,
    TrackDownloadStatus,
)
from app.exceptions.download import TrackAlreadyExistsError
from app.services.download_queue import enqueue_track, bulk_enqueue_tracks
from app.services.playlist import import_playlist
from app.services.playlist_manager import export_m3u, save_database_playlist, begin_playlist_refresh, append_playlist_batch, complete_playlist_refresh
from app.services.spotify.playlist_batches import playlist_batches
from app.services.spotify.url import spotify_resource



def download_resolved_playlist(
    db: Session,
    playlist,
    *,
    source_provider: str,
    source_id: str,
) -> PlaylistDownloadSummary:
    """
    A unified entrypoint for massive playlist downloading.
    Handles legacy full objects (like YT Music) and chunked progressive (Spotify).
    """
    db_playlist = save_database_playlist(
        db,
        source_id,
        playlist,
        source_provider=source_provider,
    )

    # We create a dummy task id just for tracking purposes inside bulk_enqueue_tracks,
    # or rely on it creating one implicitly. The queue route sets up its own task for one-offs.
    from app.services.task_service import create_task
    from app.domain.task import TaskType
    task = create_task(
        db=db,
        name=playlist.name,
        spotify_url=playlist.url,
        task_type=TaskType.PLAYLIST_DOWNLOAD,
        total_items=0,
    )

    owned = 0
    queued = 0
    already_queued = 0
    track_results: list[TrackDownloadResult] = []

    if source_provider == "spotify":
        # We process it as chunks because the full playlist object passed down
        # might be a dummy stub we just instantiated to bootstrap the db playlist.
        begin_playlist_refresh(db, db_playlist)

        discovered_count = 0
        for tracks in playlist_batches(playlist.url):
            append_playlist_batch(db, db_playlist.id, tracks, discovered_count)

            # For each chunk, queue
            for track in tracks:
                try:
                    result = enqueue_track(
                        db=db,
                        track=track,
                        task_id=task.id,
                        queue_position=discovered_count + 1,
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
                discovered_count += 1

        complete_playlist_refresh(db, db_playlist)

        task.total_items = discovered_count
        db.commit()
    else:
        # Legacy full iteration (YouTube Music, which hasn't been paginated yet)
        for position, track in enumerate(playlist.tracks, 1):
            try:
                result = enqueue_track(
                    db=db,
                    track=track,
                    task_id=task.id,
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

    export_m3u(db, db_playlist, domain_tracks=None)

    return PlaylistDownloadSummary(
        playlist_name=playlist.name,
        total=task.total_items if source_provider == "spotify" else len(playlist.tracks),
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
    # First just get high level info quickly to stub the playlist
    from app.services.spotify.metadata import _extract_id, get_client
    from app.domain.playlist import Playlist

    playlist_id = _extract_id(url, "playlist")

    try:
        spotify = get_client()
        playlist_info = spotify.playlist(playlist_id, fields="name")
        name = playlist_info.get("name", "Unknown Playlist") if playlist_info else "Unknown Playlist"
    except Exception:
        name = "One-off Mix" if playlist_id == "one-off-playlist" else "Unknown Playlist"

    playlist = Playlist(
        name=name,
        url=url,
        tracks=[] # The paginator will retrieve tracks incrementally
    )

    resource, spotify_id = spotify_resource(url)
    if resource != "playlist":
        raise ValueError("Only Spotify playlists can be downloaded as playlists.")

    return download_resolved_playlist(
        db,
        playlist,
        source_provider="spotify",
        source_id=spotify_id,
    )
