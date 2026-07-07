import json
import subprocess

from app.core.config import get_settings
from app.domain.playlist import Playlist
from app.mappers.spotdl import spotdl_song_to_track
from app.schemas.spotdl import SpotDLSong


class SpotDLClient:
    def __init__(self):
        self.settings = get_settings()

    def playlist(self, url: str) -> Playlist:
        result = self._run(
            [
                "save",
                url,
                "--audio",
                *self._audio_providers(),
                "--save-file",
                "-",
            ]
        )

        if result.returncode != 0:
            raise RuntimeError(result.stderr)

        songs = self._extract_json(result.stdout)

        validated = [
            SpotDLSong.model_validate(song)
            for song in songs
        ]

        tracks = [
            spotdl_song_to_track(song)
            for song in validated
        ]

        if not validated:
            raise RuntimeError("Playlist is empty.")

        first = validated[0]

        return Playlist(
            name=first.list_name or "Unknown Playlist",
            url=first.list_url or "",
            tracks=tracks,
        )

    def _audio_providers(self) -> list[str]:
        return [
            provider.strip()
            for provider in self.settings.audio_providers.split(",")
            if provider.strip()
        ]

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.settings.spotdl_path, *args],
            capture_output=True,
            text=True,
        )

    @staticmethod
    def _extract_json(stdout: str):
        start = stdout.find("[")

        if start == -1:
            raise RuntimeError("SpotDL did not return JSON.")

        return json.loads(stdout[start:])