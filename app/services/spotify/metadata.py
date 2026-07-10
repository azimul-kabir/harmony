from urllib.parse import urlparse

from app.domain.track import Track
from app.services.spotify.client import get_client


def resolve_track(spotify_url: str) -> Track:
    """
    Resolve a Spotify track URL into Harmony's Track model.
    """

    spotify = get_client()

    track_id = _extract_track_id(spotify_url)

    data = spotify.track(track_id)

    if data is None:
        raise RuntimeError(
            f"Spotify returned no metadata for {spotify_url}"
        )

    album = data.get("album")

    if album is None:
        raise RuntimeError(
            f"Spotify returned incomplete metadata for {spotify_url}"
        )

    return Track(
        spotify_url=spotify_url,
        title=data.get("name"),
        artist=", ".join(
            artist["name"]
            for artist in data.get("artists", [])
        ),
        album=album.get("name"),
        album_artist=", ".join(
            artist["name"]
            for artist in album.get("artists", [])
        ),
        track=data.get("track_number"),
        disc=data.get("disc_number"),
        year=int(album["release_date"][:4])
        if album.get("release_date")
        else None,
    )


def _extract_track_id(url: str) -> str:
    path = urlparse(url).path

    parts = path.strip("/").split("/")

    if len(parts) != 2 or parts[0] != "track":
        raise ValueError("Invalid Spotify track URL.")

    return parts[1]