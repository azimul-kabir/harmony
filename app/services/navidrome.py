from __future__ import annotations

import hashlib
import secrets
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings


class NavidromeError(RuntimeError):
    def __init__(self, message: str, *, code: str = "navidrome_unavailable") -> None:
        super().__init__(message)
        self.code = code


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
        extra_params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if not self.configured:
            raise NavidromeError(
                "Navidrome credentials are not configured.",
                code="navidrome_not_configured",
            )
        params = self._auth_params()
        params.update(extra_params or {})
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.navidrome_timeout_seconds,
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                response = await client.get(self._endpoint(action), params=params)
                response.raise_for_status()
                payload = response.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as error:
            raise NavidromeError(
                "Harmony could not reach Navidrome.",
                code="navidrome_unavailable",
            ) from error

        envelope = payload.get("subsonic-response", {})
        if envelope.get("status") != "ok":
            error = envelope.get("error") or {}
            raise NavidromeError(
                error.get("message") or "Navidrome rejected the request.",
                code="navidrome_api_error",
            )
        return envelope

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
