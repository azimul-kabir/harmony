from urllib.parse import urlparse

from app.domain.track import Track
from app.services.spotify.client import get_client


def resolve_track(spotify_url: str) -> Track:
    """
    Resolve a Spotify track URL into Harmony's Track model.
    """

    spotify = get_client()

    track_id = _extract_id(
        spotify_url,
        "track",
    )

    data = spotify.track(track_id)

    if data is None:
        raise RuntimeError(f"Spotify returned no metadata for {spotify_url}")

    album = data.get("album")

    if album is None:
        raise RuntimeError(f"Spotify returned incomplete metadata for {spotify_url}")

    artists = [artist["name"] for artist in (data.get("artists") or [])]

    album_artists = [artist["name"] for artist in (album.get("artists") or [])]

    images = album.get("images") or []

    release_date = album.get("release_date")

    year = int(release_date[:4]) if release_date else None

    return Track(
        title=data.get("name"),
        artist=", ".join(artists),
        artists=artists,
        album=album.get("name"),
        album_artist=", ".join(album_artists),
        track=data.get("track_number"),
        disc=data.get("disc_number"),
        year=year,
        duration=data.get("duration_ms"),
        spotify_track_id=data.get("id"),
        spotify_album_id=album.get("id"),
        spotify_url=spotify_url,
        isrc=(data.get("external_ids") or {}).get("isrc"),
        cover_url=images[0]["url"] if images else None,
    )


def resolve_album(
    spotify_url: str,
) -> list[Track]:
    """
    Resolve a Spotify album URL into a list of Harmony Track objects.
    """

    spotify = get_client()

    album_id = _extract_id(
        spotify_url,
        "album",
    )

    album = spotify.album(album_id)

    if album is None:
        raise RuntimeError(f"Spotify returned no metadata for {spotify_url}")

    tracks_data = album.get("tracks")

    if tracks_data is None:
        raise RuntimeError(
            f"Spotify returned incomplete album metadata for {spotify_url}"
        )

    album_artists = [artist["name"] for artist in (album.get("artists") or [])]

    images = album.get("images") or []

    release_date = album.get("release_date")

    year = int(release_date[:4]) if release_date else None

    tracks: list[Track] = []

    for item in tracks_data.get("items", []):
        artists = [artist["name"] for artist in (item.get("artists") or [])]

        external_urls = item.get("external_urls") or {}

        tracks.append(
            Track(
                title=item.get("name"),
                artist=", ".join(artists),
                artists=artists,
                album=album.get("name"),
                album_artist=", ".join(album_artists),
                track=item.get("track_number"),
                disc=item.get("disc_number"),
                year=year,
                duration=item.get("duration_ms"),
                spotify_track_id=item.get("id"),
                spotify_album_id=album.get("id"),
                spotify_url=external_urls.get("spotify"),
                # Album endpoint doesn't provide ISRC.
                isrc=None,
                cover_url=images[0]["url"] if images else None,
            )
        )

    return tracks


def resolve_playlist(
    spotify_url: str,
) -> list[Track]:
    """
    Resolve a Spotify playlist URL into a list of Harmony Track objects.
    """

    spotify = get_client()

    playlist_id = _extract_id(
        spotify_url,
        "playlist",
    )

    playlist = spotify.playlist(playlist_id)

    if playlist is None:
        raise RuntimeError(f"Spotify returned no metadata for {spotify_url}")

    tracks: list[Track] = []

    for item in playlist.get("tracks", {}).get("items", []):
        data = item.get("track")

        if data is None:
            continue

        album = data.get("album")

        if album is None:
            continue

        artists = [artist["name"] for artist in (data.get("artists") or [])]

        album_artists = [artist["name"] for artist in (album.get("artists") or [])]

        images = album.get("images") or []

        release_date = album.get("release_date")

        year = int(release_date[:4]) if release_date else None

        external_urls = data.get("external_urls") or {}

        tracks.append(
            Track(
                title=data.get("name"),
                artist=", ".join(artists),
                artists=artists,
                album=album.get("name"),
                album_artist=", ".join(album_artists),
                track=data.get("track_number"),
                disc=data.get("disc_number"),
                year=year,
                duration=data.get("duration_ms"),
                spotify_track_id=data.get("id"),
                spotify_album_id=album.get("id"),
                spotify_url=external_urls.get("spotify"),
                isrc=(data.get("external_ids") or {}).get("isrc"),
                cover_url=images[0]["url"] if images else None,
            )
        )

    return tracks


def _extract_id(
    url: str,
    expected_type: str,
) -> str:
    path = urlparse(url).path

    parts = path.strip("/").split("/")

    if len(parts) != 2 or parts[0] != expected_type:
        raise ValueError(f"Invalid Spotify {expected_type} URL.")

    return parts[1]
