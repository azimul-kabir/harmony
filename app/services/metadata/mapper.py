from app.domain.metadata.album import AlbumMetadata
from app.domain.metadata.artist import ArtistMetadata
from app.domain.metadata.track import TrackMetadata
from app.domain.track import Track


def metadata_to_track(metadata: TrackMetadata) -> Track:
    album_artist = None

    if metadata.album:
        album_artist = metadata.album.album_artist

    return Track(
        title=metadata.title,
        artist=", ".join(a.name for a in metadata.artists),

        album=metadata.album.title if metadata.album else None,
        album_artist=album_artist,

        track=metadata.track_number,
        disc=metadata.disc_number,

        duration=(
            metadata.duration_ms / 1000
            if metadata.duration_ms is not None
            else None
        ),

        spotify_track_id=metadata.spotify_track_id,
        spotify_url=metadata.spotify_url,
        isrc=metadata.isrc,
    )