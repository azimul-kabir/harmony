"""Incremental access to SpotDL's pinned, unofficial Spotify playlist reader."""

from dataclasses import dataclass
from importlib.metadata import version
from typing import Iterator
from urllib.parse import urlparse

from SpotipyFree.Formatter import SpotifyFormatter
from spotapi import PublicPlaylist

from app.domain.track import Track


SUPPORTED_SPOTDL_VERSION = "4.5.2"


@dataclass(frozen=True, slots=True)
class SpotifyPlaylistMetadata:
    name: str
    url: str


class UnofficialSpotifyPlaylistReader:
    """Read public playlists page-by-page without Spotify Web API credentials."""

    def __init__(self, url: str, batch_size: int = 50) -> None:
        if batch_size < 1:
            raise ValueError("Playlist batch size must be positive.")
        self.url = url
        self.playlist_id = _playlist_id(url)
        self.batch_size = batch_size
        self._playlist = PublicPlaylist(self.playlist_id)

    def metadata(self) -> SpotifyPlaylistMetadata:
        _check_compatibility()
        payload = self._playlist.get_playlist_info()["data"]["playlistV2"]
        formatted = SpotifyFormatter.formatPlaylist(payload)
        return SpotifyPlaylistMetadata(
            name=formatted.get("name") or "Unknown Playlist",
            url=self.url,
        )

    def batches(self) -> Iterator[list[Track]]:
        _check_compatibility()
        pending: list[Track] = []
        for page in self._playlist.paginate_playlist():
            for raw_item in page.get("items", []):
                track = _format_track(raw_item)
                if track is None:
                    continue
                pending.append(track)
                if len(pending) == self.batch_size:
                    yield pending
                    pending = []
        if pending:
            yield pending


def _playlist_id(url: str) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.netloc not in {"open.spotify.com", "www.open.spotify.com"}:
        raise ValueError("Enter a public Spotify playlist URL.")
    try:
        playlist_index = parts.index("playlist")
        playlist_id = parts[playlist_index + 1]
    except (ValueError, IndexError) as error:
        raise ValueError("Enter a public Spotify playlist URL.") from error
    if not playlist_id:
        raise ValueError("Enter a public Spotify playlist URL.")
    return playlist_id


def _check_compatibility() -> None:
    installed = version("spotdl")
    if installed != SUPPORTED_SPOTDL_VERSION:
        raise RuntimeError(
            "Incremental Spotify playlist import requires SpotDL "
            f"{SUPPORTED_SPOTDL_VERSION}; found {installed}."
        )


def _format_track(raw_item: dict) -> Track | None:
    try:
        meta = SpotifyFormatter.formatPlaylistTrack(raw_item)["track"]
        if meta.get("is_local") or meta.get("type") != "track":
            return None
        artists = [artist["name"] for artist in meta.get("artists", []) if artist.get("name")]
        track_id = meta.get("id")
        if not track_id or not artists or not meta.get("name"):
            return None
        album = meta.get("album") or {}
        images = album.get("images") or []
        cover_url = next(
            (image.get("url") for image in images if image.get("url")),
            None,
        )
        return Track(
            title=meta["name"],
            artist=artists[0],
            artists=artists,
            album=album.get("name"),
            album_artist=next(
                (
                    artist.get("name")
                    for artist in album.get("artists", [])
                    if artist.get("name")
                ),
                None,
            ),
            track=meta.get("track_number"),
            disc=meta.get("disc_number"),
            duration=(meta.get("duration_ms") or 0) / 1000,
            year=int(album["release_date"][:4])
            if str(album.get("release_date", ""))[:4].isdigit()
            else None,
            cover_url=cover_url,
            spotify_track_id=track_id,
            spotify_album_id=album.get("id"),
            spotify_url=meta.get("external_urls", {}).get("spotify"),
            source_provider="spotify",
            source_item_id=track_id,
            source_url=meta.get("external_urls", {}).get("spotify"),
        )
    except (KeyError, TypeError, AttributeError):
        return None
