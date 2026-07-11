from app.database.crud_sync_sources import get_all_sync_sources
from app.services.playlist_download import download_playlist
from app.services.spotify.metadata import resolve_album
from app.services.download_queue import enqueue_track


def sync_all_sources(db):
    added = 0

    for source in get_all_sync_sources(db):
        if not source.enabled:
            continue

        if source.type == "playlist":
            summary = download_playlist(
                db=db,
                url=source.spotify_url,
            )

            added += summary.get("queued", 0)

        elif source.type == "album":
            tracks = resolve_album(source.spotify_url)

            for track in tracks:
                result = enqueue_track(
                    db=db,
                    track=track,
                )

                if result.status.value == "queued":
                    added += 1

    return {
        "sources": len(get_all_sync_sources(db)),
        "queued": added,
    }