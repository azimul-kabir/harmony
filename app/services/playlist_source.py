"""Provider-neutral parsing for durable playlist sources."""

from dataclasses import dataclass
import re
from urllib.parse import parse_qs, urlparse


_SPOTIFY_ID = re.compile(r"^[A-Za-z0-9]+$")
_YOUTUBE_LIST_ID = re.compile(r"^[A-Za-z0-9_-]{6,200}$")


class PlaylistSourceError(ValueError):
    def __init__(self, message: str, code: str = "playlist_url_invalid") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ParsedPlaylistSource:
    provider: str
    resource_type: str
    external_id: str
    canonical_url: str


def parse_playlist_source(value: str) -> ParsedPlaylistSource:
    raw = (value or "").strip()
    if not raw:
        raise PlaylistSourceError("A playlist URL is required.")

    if raw.lower().startswith("spotify:"):
        parts = raw.split(":")
        if len(parts) != 3 or parts[1] != "playlist" or not _SPOTIFY_ID.fullmatch(parts[2]):
            if len(parts) > 1 and parts[1] != "playlist":
                raise PlaylistSourceError("Only playlist URLs are supported.")
            raise PlaylistSourceError("Invalid Spotify playlist URL.")
        item_id = parts[2]
        return ParsedPlaylistSource("spotify", "playlist", item_id, f"https://open.spotify.com/playlist/{item_id}")

    normalized = raw if "://" in raw else f"https://{raw}"
    parsed = urlparse(normalized)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    query = parse_qs(parsed.query)

    if host == "open.spotify.com":
        parts = [part for part in parsed.path.split("/") if part]
        if not parts or parts[0] != "playlist":
            raise PlaylistSourceError("Only playlist URLs are supported.")
        if len(parts) != 2 or not _SPOTIFY_ID.fullmatch(parts[1]):
            raise PlaylistSourceError("Invalid Spotify playlist URL.")
        return ParsedPlaylistSource("spotify", "playlist", parts[1], f"https://open.spotify.com/playlist/{parts[1]}")

    if host == "music.youtube.com":
        if parsed.path != "/playlist":
            raise PlaylistSourceError("Only playlist URLs are supported.")
        item_id = (query.get("list") or [""])[0].strip()
        if not _YOUTUBE_LIST_ID.fullmatch(item_id):
            raise PlaylistSourceError("Invalid YouTube Music playlist URL.")
        return ParsedPlaylistSource("youtube_music", "playlist", item_id, f"https://music.youtube.com/playlist?list={item_id}")

    if host in {"youtube.com", "m.youtube.com", "youtu.be"}:
        raise PlaylistSourceError("Only YouTube Music playlist URLs are supported.")
    raise PlaylistSourceError("Unsupported playlist provider.", "playlist_provider_unsupported")
