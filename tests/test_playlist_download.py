from sqlalchemy import select

from app.database.models import Playlist, PlaylistTrack, SyncSource
from app.database.session import SessionLocal
from app.domain.playlist import Playlist as DomainPlaylist
from app.domain.queue import QueueResult, QueueStatus
from app.domain.track import Track
from app.services import playlist_download


def test_playlist_download_saves_playlist_without_creating_sync_source(monkeypatch):
    url = "https://open.spotify.com/playlist/one-off-playlist"
    domain_playlist = DomainPlaylist(
        name="One-off Mix",
        url=url,
        tracks=[
            Track(
                title="First",
                artist="Artist",
                spotify_track_id="track-1",
            ),
            Track(
                title="Second",
                artist="Artist",
                spotify_track_id="track-2",
            ),
        ],
    )
    queued_positions = []
    exported = []

    monkeypatch.setattr(
        playlist_download,
        "import_playlist",
        lambda requested_url: domain_playlist,
    )
    monkeypatch.setattr(
        playlist_download,
        "enqueue_track",
        lambda db, track, queue_position=None: (
            queued_positions.append(queue_position)
            or QueueResult(job_id=queue_position, status=QueueStatus.CREATED)
        ),
    )
    monkeypatch.setattr(
        playlist_download,
        "export_m3u",
        lambda db, playlist, domain_tracks=None: (
            exported.append((playlist.spotify_id, domain_tracks))
            or 0
        ),
    )

    db = SessionLocal()
    try:
        summary = playlist_download.download_playlist(db, url)

        saved = db.scalar(
            select(Playlist).where(Playlist.spotify_id == "one-off-playlist")
        )
        assert saved is not None
        assert saved.name == "One-off Mix"
        assert saved.last_synced_at is None
        assert [
            (track.spotify_track_id, track.position)
            for track in db.scalars(
                select(PlaylistTrack)
                .where(PlaylistTrack.playlist_id == saved.id)
                .order_by(PlaylistTrack.position)
            )
        ] == [("track-1", 1), ("track-2", 2)]
        assert db.scalar(select(SyncSource.id)) is None
        assert exported == [("one-off-playlist", domain_playlist.tracks)]
        assert queued_positions == [1, 2]
        assert summary.playlist_name == "One-off Mix"
        assert summary.queued == 2
    finally:
        db.close()
