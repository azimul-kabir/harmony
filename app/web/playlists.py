from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.database.models import Playlist, SyncSource
from app.services.playlist_manager import (
    count_m3u_entries,
    playlist_artwork_path,
    playlist_file_path,
)
from app.web.templates import templates, template_context

router = APIRouter(tags=["web"])


def _playlist_sync_status(playlist: Playlist, exported_count: int) -> str:
    """Describe export health independently from how the playlist was created."""
    if exported_count == playlist.track_count:
        return "ready"
    if exported_count:
        return "partial"
    if playlist.last_synced_at:
        return "failed"
    return "pending"


@router.get("/playlists")
def playlists_page(request: Request, db: Session = Depends(get_db)):
    playlists = (
        db.query(Playlist)
        .where(Playlist.playlist_kind != "smart")
        .order_by(Playlist.name)
        .all()
    )
    sources = {
        (source.provider or "spotify", source.external_id or source.spotify_id): source
        for source in db.query(SyncSource).all()
    }
    playlist_cards = []
    for playlist in playlists:
        file_path = playlist_file_path(playlist.name)
        exported_count = count_m3u_entries(file_path)
        playlist_cards.append(
            {
                "playlist": playlist,
                "source": sources.get((playlist.source_provider or "spotify", playlist.source_external_id or playlist.spotify_id)),
                "exported_count": exported_count,
                "m3u_exists": file_path.is_file(),
                "artwork_exists": playlist_artwork_path(playlist.name) is not None,
                "type_label": "Imported",
                "sync_status": _playlist_sync_status(playlist, exported_count),
            }
        )

    return templates.TemplateResponse(
        "playlists.html",
        template_context(
            request=request, 
            page="playlists",
            playlists=playlist_cards,
        ),
    )
