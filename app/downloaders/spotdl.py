import json
import subprocess

from app.core.config import get_settings
from app.domain.playlist import Playlist
from app.mappers.spotdl import spotdl_song_to_track
from app.schemas.spotdl import SpotDLSong


class SpotDLClient:
    def __init__(self):
        self.settings = get_settings()

    @staticmethod
    def _extract_json(stdout: str):
        start = stdout.find("[")

        if start == -1:
            raise RuntimeError("SpotDL did not return JSON.")

        return json.loads(stdout[start:])

    def playlist(self, url: str) -> Playlist:
        result = subprocess.run(
            [
                self.settings.spotdl_path,
                "save",
                url,
                "--save-file",
                "-",
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(result.stderr)

        songs = self._extract_json(result.stdout)

        validated = [
            SpotDLSong.model_validate(song)
            for song in songs
        ]

        validated.sort(
            key=lambda song: song.list_position or 0
        )

        tracks = [
            spotdl_song_to_track(song)
            for song in validated
        ]

        if not validated:
            return Playlist(
                name="",
                url=url,
                tracks=[],
            )

        return Playlist(
            name=validated[0].list_name or "",
            url=validated[0].list_url or url,
            tracks=tracks,
        )