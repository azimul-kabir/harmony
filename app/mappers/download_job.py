import json

from app.database.models import DownloadJob
from app.domain.track import Track


def download_job_to_track(job: DownloadJob) -> Track:
    """Reconstruct the canonical metadata persisted with queued work."""
    return Track(
        title=job.title, artist=job.artist, album=job.album,
        album_artist=job.album_artist, track=job.track, disc=job.disc,
        year=job.year, isrc=job.isrc, cover_url=job.cover_url,
        spotify_track_id=job.spotify_track_id, spotify_url=job.source_url,
        source_provider=job.source_provider or "spotify",
        source_item_id=job.source_item_id, source_url=job.source_url,
        genre=job.genre, duration=job.duration,
        spotify_artist_ids=json.loads(job.spotify_artist_ids or "[]"),
        genre_provenance=job.genre_provenance,
    )
