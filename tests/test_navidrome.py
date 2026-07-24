import asyncio
import hashlib
from types import SimpleNamespace

import httpx
import pytest

from app.services.navidrome import NavidromeClient, NavidromeError


def _settings(**overrides):
    values = {
        "navidrome_url": "http://navidrome:4533",
        "navidrome_username": "harmony",
        "navidrome_password": "secret",
        "navidrome_timeout_seconds": 2,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_status_uses_token_auth_and_normalizes_scan_state():
    def handler(request):
        params = request.url.params
        assert request.url.path == "/rest/getScanStatus"
        assert params["u"] == "harmony"
        assert params["f"] == "json"
        assert params["t"] == hashlib.md5(
            f"secret{params['s']}".encode()
        ).hexdigest()
        return httpx.Response(
            200,
            json={
                "subsonic-response": {
                    "status": "ok",
                    "serverVersion": "0.58.0",
                    "scanStatus": {
                        "scanning": True,
                        "count": 42,
                        "lastScan": "2026-07-24T04:00:00Z",
                        "folderCount": 2,
                    },
                }
            },
        )

    status = asyncio.run(
        NavidromeClient(
            _settings(),
            transport=httpx.MockTransport(handler),
        ).status()
    )

    assert status == {
        "configured": True,
        "reachable": True,
        "scanning": True,
        "scan_count": 42,
        "last_scan": "2026-07-24T04:00:00Z",
        "folder_count": 2,
        "server_version": "0.58.0",
    }


def test_status_is_safe_when_not_configured():
    status = asyncio.run(
        NavidromeClient(_settings(navidrome_password="")).status()
    )

    assert status["configured"] is False
    assert status["reachable"] is False
    assert status["error"] is None


def test_status_reports_connection_failure_without_exposing_credentials():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    status = asyncio.run(
        NavidromeClient(
            _settings(navidrome_password="do-not-leak"),
            transport=httpx.MockTransport(handler),
        ).status()
    )

    assert status["configured"] is True
    assert status["reachable"] is False
    assert "do-not-leak" not in status["error"]


@pytest.mark.parametrize("full_scan", [False, True])
def test_start_scan_passes_full_scan_flag(full_scan):
    def handler(request):
        assert request.url.path == "/rest/startScan"
        assert request.url.params["fullScan"] == str(full_scan).lower()
        return httpx.Response(
            200,
            json={
                "subsonic-response": {
                    "status": "ok",
                    "scanStatus": {"scanning": True},
                }
            },
        )

    result = asyncio.run(
        NavidromeClient(
            _settings(),
            transport=httpx.MockTransport(handler),
        ).start_scan(full_scan=full_scan)
    )

    assert result["accepted"] is True
    assert result["full_scan"] is full_scan
    assert result["scanning"] is True


def test_api_errors_become_clean_navidrome_errors():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "subsonic-response": {
                    "status": "failed",
                    "error": {"code": 40, "message": "Wrong username or password"},
                }
            },
        )
    )

    with pytest.raises(NavidromeError) as caught:
        asyncio.run(
            NavidromeClient(_settings(), transport=transport).start_scan()
        )

    assert caught.value.code == "navidrome_api_error"
    assert str(caught.value) == "Wrong username or password"


def test_url_rejects_embedded_credentials():
    client = NavidromeClient(
        _settings(navidrome_url="http://user:password@navidrome:4533")
    )

    with pytest.raises(NavidromeError) as caught:
        client._endpoint("getScanStatus")

    assert caught.value.code == "navidrome_invalid_url"
