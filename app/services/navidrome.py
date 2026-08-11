from __future__ import annotations

import hashlib
import secrets
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlparse

import httpx
import asyncio

from app.core.config import get_settings


class NavidromeError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "navidrome_unavailable",
        api_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.api_code = api_code


class NavidromeClient:
    """Small Subsonic client for Navidrome health and scan controls."""

    def __init__(self, settings=None, *, transport=None) -> None:
        self.settings = settings or get_settings()
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.navidrome_url.strip()
            and self.settings.navidrome_username.strip()
            and self.settings.navidrome_password
        )

    def _endpoint(self, action: str) -> str:
        base_url = self.settings.navidrome_url.strip().rstrip("/")
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise NavidromeError(
                "NAVIDROME_URL must be an absolute HTTP or HTTPS URL.",
                code="navidrome_invalid_url",
            )
        if parsed.username or parsed.password:
            raise NavidromeError(
                "NAVIDROME_URL must not contain credentials.",
                code="navidrome_invalid_url",
            )
        return f"{base_url}/rest/{action}"

    def _auth_params(self) -> dict[str, str]:
        salt = secrets.token_hex(6)
        token = hashlib.md5(  # noqa: S324 - required by the Subsonic API
            f"{self.settings.navidrome_password}{salt}".encode()
        ).hexdigest()
        return {
            "u": self.settings.navidrome_username,
            "t": token,
            "s": salt,
            "v": "1.16.1",
            "c": "Harmony",
            "f": "json",
        }

    async def _request(
        self,
        action: str,
        *,
        extra_params: dict[str, str | Sequence[str]] | None = None,
    ) -> dict[str, Any]:
        if not self.configured:
            raise NavidromeError(
                "Navidrome credentials are not configured.",
                code="navidrome_not_configured",
            )
        params = self._auth_params()
        params.update(extra_params or {})
        attempts = max(1, int(getattr(self.settings, "navidrome_max_retries", 2)) + 1)
        for attempt in range(attempts):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(
                        self.settings.navidrome_timeout_seconds,
                        connect=self.settings.navidrome_timeout_seconds,
                    ),
                    follow_redirects=False,
                    transport=self.transport,
                ) as client:
                    response = await client.get(self._endpoint(action), params=params)
                    if response.status_code in {401, 403}:
                        raise NavidromeError(
                            "Navidrome authentication failed.",
                            code="authentication_failed",
                        )
                    if response.status_code >= 500 and attempt + 1 < attempts:
                        await asyncio.sleep(0.1 * (2**attempt))
                        params.update(self._auth_params())
                        continue
                    response.raise_for_status()
                    payload = response.json()
                    break
            except NavidromeError:
                raise
            except httpx.TimeoutException as error:
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.1 * (2**attempt))
                    params.update(self._auth_params())
                    continue
                raise NavidromeError(
                    "Navidrome request timed out.", code="timeout"
                ) from error
            except httpx.RequestError as error:
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.1 * (2**attempt))
                    params.update(self._auth_params())
                    continue
                raise NavidromeError(
                    "Harmony could not connect to Navidrome.", code="connection_failed"
                ) from error
            except httpx.HTTPStatusError as error:
                raise NavidromeError(
                    "Navidrome returned a server error.", code="navidrome_api_error"
                ) from error
            except ValueError as error:
                raise NavidromeError(
                    "Navidrome returned malformed JSON.",
                    code="invalid_playlist_response",
                ) from error

        envelope = (
            payload.get("subsonic-response") if isinstance(payload, dict) else None
        )
        if not isinstance(envelope, dict):
            raise NavidromeError(
                "Navidrome returned an invalid response.",
                code="invalid_playlist_response",
            )
        if envelope.get("status") != "ok":
            error = envelope.get("error") or {}
            api_code = error.get("code")
            code = (
                "authentication_failed"
                if api_code in {40, 41, 42, 44}
                else "permission_denied"
                if api_code == 50
                else "navidrome_api_error"
            )
            raise NavidromeError(
                "Navidrome authentication failed."
                if code == "authentication_failed"
                else "Navidrome rejected the request.",
                code=code,
                api_code=api_code,
            )
        return envelope

    @staticmethod
    def _as_list(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return [value]
        return []

    @staticmethod
    def _status_payload(envelope: dict[str, Any]) -> dict[str, Any]:
        scan = envelope.get("scanStatus") or {}
        return {
            "configured": True,
            "reachable": True,
            "scanning": bool(scan.get("scanning", False)),
            "scan_count": int(scan.get("count") or 0),
            "last_scan": scan.get("lastScan"),
            "folder_count": int(scan.get("folderCount") or 0),
            "server_version": envelope.get("serverVersion"),
        }

    async def status(self) -> dict[str, Any]:
        if not self.configured:
            return {
                "configured": False,
                "reachable": False,
                "scanning": False,
                "scan_count": 0,
                "last_scan": None,
                "folder_count": 0,
                "server_version": None,
                "error": None,
            }
        try:
            return self._status_payload(await self._request("getScanStatus"))
        except NavidromeError as error:
            return {
                "configured": True,
                "reachable": False,
                "scanning": False,
                "scan_count": 0,
                "last_scan": None,
                "folder_count": 0,
                "server_version": None,
                "error": str(error),
            }

    async def start_scan(self, *, full_scan: bool = False) -> dict[str, Any]:
        envelope = await self._request(
            "startScan",
            extra_params={"fullScan": str(full_scan).lower()},
        )
        return {
            **self._status_payload(envelope),
            "accepted": True,
            "full_scan": full_scan,
        }

    async def search_songs(
        self, query: str, *, count: int = 25
    ) -> list[dict[str, Any]]:
        envelope = await self._request(
            "search3",
            extra_params={
                "query": query,
                "songCount": str(max(1, count)),
                "songOffset": "0",
                "albumCount": "0",
                "artistCount": "0",
            },
        )
        result = envelope.get("searchResult3") or {}
        return self._as_list(result.get("song"))

    async def library_songs(self, *, page_size: int = 500) -> list[dict[str, Any]]:
        """Return the user's Navidrome songs, including playback/star metadata."""
        size = max(1, min(int(page_size), 500))
        songs: list[dict[str, Any]] = []
        offset = 0
        while True:
            envelope = await self._request(
                "search3",
                extra_params={
                    "query": "",
                    "songCount": str(size),
                    "songOffset": str(offset),
                    "albumCount": "0",
                    "artistCount": "0",
                },
            )
            page = self._as_list((envelope.get("searchResult3") or {}).get("song"))
            songs.extend(page)
            if len(page) < size:
                return songs
            offset += size

    async def get_song(self, song_id: str) -> dict[str, Any]:
        envelope = await self._request("getSong", extra_params={"id": song_id})
        song = envelope.get("song")
        if not isinstance(song, dict):
            raise NavidromeError(
                "Navidrome returned an invalid song response.",
                code="navidrome_invalid_response",
            )
        return song

    async def get_playlists(self) -> list[dict[str, Any]]:
        envelope = await self._request("getPlaylists")
        playlists = envelope.get("playlists") or {}
        return self._as_list(playlists.get("playlist"))

    async def get_albums(self, *, size: int = 500) -> list[dict[str, Any]]:
        """Return every album visible to the configured Navidrome user."""
        albums: list[dict[str, Any]] = []
        offset = 0
        page_size = max(1, min(int(size), 500))
        while True:
            envelope = await self._request(
                "getAlbumList2",
                extra_params={
                    "type": "alphabeticalByName",
                    "size": str(page_size),
                    "offset": str(offset),
                },
            )
            page = self._as_list((envelope.get("albumList2") or {}).get("album"))
            albums.extend(page)
            if len(page) < page_size:
                return albums
            offset += page_size

    async def get_artists(self) -> list[dict[str, Any]]:
        """Return every artist visible to the configured Navidrome user."""
        envelope = await self._request("getArtists")
        indexes = self._as_list((envelope.get("artists") or {}).get("index"))
        return [
            artist
            for index in indexes
            for artist in self._as_list(index.get("artist"))
        ]

    async def get_playlist(self, playlist_id: str) -> dict[str, Any]:
        if not isinstance(playlist_id, str) or not playlist_id.strip():
            raise ValueError("A valid playlist ID is required.")
        envelope = await self._request("getPlaylist", extra_params={"id": playlist_id})
        playlist = envelope.get("playlist")
        if not isinstance(playlist, dict):
            raise NavidromeError(
                "Navidrome returned an invalid playlist response.",
                code="navidrome_invalid_response",
            )
        return playlist

    async def ping(self) -> dict[str, Any]:
        envelope = await self._request("ping")
        return {"ok": True, "server_version": envelope.get("serverVersion")}

    async def replace_playlist(
        self,
        *,
        name: str,
        song_ids: Sequence[str],
        playlist_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, str | Sequence[str]] = {
            "songId": list(song_ids),
        }
        if playlist_id:
            params["playlistId"] = playlist_id
        else:
            params["name"] = name
        envelope = await self._request("createPlaylist", extra_params=params)
        playlist = envelope.get("playlist")
        if not isinstance(playlist, dict):
            raise NavidromeError(
                "Navidrome returned an invalid playlist response.",
                code="navidrome_invalid_response",
            )
        return playlist
