import json
from typing import Generator, List

from spotapi import PublicPlaylist
from SpotipyFree.Formatter import SpotifyFormatter

from app.domain.track import Track

def playlist_batches(playlist_url: str, batch_size: int = 50) -> Generator[List[Track], None, None]:
    playlist_id = playlist_url.split("playlist/")[-1].split("?")[0] if "playlist" in playlist_url else playlist_url

    pending = []
    position = 0

    for provider_page in PublicPlaylist(playlist_id).paginate_playlist():
        for raw_item in provider_page["items"]:
            if not raw_item.get("itemV3"):
                continue # Skip items that are not properly structured
            metadata = SpotifyFormatter.formatPlaylistTrack(raw_item)

            track_data = metadata.get("track", {})
            artists_data = track_data.get("artists", [])
            album_data = track_data.get("album", {})

            title = track_data.get("name")
            artist = artists_data[0].get("name") if artists_data else None
            spotify_track_id = track_data.get("id")

            duration_ms = track_data.get("duration_ms")
            duration = duration_ms / 1000.0 if duration_ms else None

            track = Track(
                title=title,
                artist=artist,
                artists=[a.get("name") for a in artists_data],
                spotify_artist_ids=[a.get("id") for a in artists_data if a.get("id")],
                spotify_track_id=spotify_track_id,
                duration=duration,
                album=album_data.get("name"),
                track=track_data.get("track_number"),
                disc=track_data.get("disc_number"),
                isrc=(track_data.get("external_ids") or {}).get("isrc"),
                spotify_url=(track_data.get("external_urls") or {}).get("spotify"),
            )

            pending.append(track)
            position += 1

            if len(pending) == batch_size:
                yield pending
                pending = []

    if pending:
        yield pending
