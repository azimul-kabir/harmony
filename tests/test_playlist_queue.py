from app.domain.playlist import Playlist
from app.domain.queue import QueueResult, QueueStatus
from app.domain.track import Track
from app.services import download_queue


def test_enqueue_playlist_uses_playlist_importer(monkeypatch):
    playlist_url = "https://open.spotify.com/playlist/playlist-1"
    created_jobs = []

    def fake_import_playlist(url: str):
        assert url == playlist_url

        return Playlist(
            name="Road Trip",
            url=playlist_url,
            tracks=[
                Track(
                    title="First Song",
                    artist="Artist",
                    spotify_url="https://open.spotify.com/track/track-1",
                ),
                Track(
                    title="Second Song",
                    artist="Artist",
                    spotify_url="https://open.spotify.com/track/track-2",
                ),
            ],
        )

    def fake_enqueue_track(db, track, task_id=None):
        created_jobs.append(track.spotify_url)
        return QueueResult(
            job_id=len(created_jobs),
            status=QueueStatus.CREATED,
        )

    monkeypatch.setattr(download_queue, "import_playlist", fake_import_playlist)
    monkeypatch.setattr(download_queue, "enqueue_track", fake_enqueue_track)

    results = download_queue.enqueue_playlist(
        db=__import__("unittest.mock").mock.MagicMock(scalar=__import__("unittest.mock").mock.MagicMock(return_value=None)),
        spotify_url=playlist_url,
    )

    assert created_jobs == [
        "https://open.spotify.com/track/track-1",
        "https://open.spotify.com/track/track-2",
    ]
    assert [result.status for result in results] == [
        QueueStatus.CREATED,
        QueueStatus.CREATED,
    ]
