from sqlalchemy.orm import Session
from app.database.crud_sync_sources import (
    create_sync_source,
    get_sync_source_by_identity,
)
from app.services.playlist_source import parse_playlist_source

def create_playlist_source(
    db: Session,
    spotify_url: str,
):
    parsed = parse_playlist_source(spotify_url)
    existing = get_sync_source_by_identity(db, parsed.provider, parsed.external_id)
    if existing:
        return existing

    # Create the source instantly without waiting 10 minutes for SpotDL.
    # The background worker will update this name during the first sync.
    return create_sync_source(
        db=db,
        type="playlist",
        provider=parsed.provider,
        external_id=parsed.external_id,
        source_url=parsed.canonical_url,
        spotify_id=(parsed.external_id if parsed.provider == "spotify" else f"{parsed.provider}:{parsed.external_id}"),
        spotify_url=parsed.canonical_url,
        name="Fetching Playlist Data...",
    )
