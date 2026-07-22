"""Typed terminal download outcomes and safe error classification."""
from __future__ import annotations

import errno
from dataclasses import dataclass


@dataclass(slots=True)
class DownloadOutcome(Exception):
    reason_code: str
    message: str
    stage: str
    provider: str = "spotdl"
    retryable: bool = False
    technical_detail: str | None = None


class DownloadSkipped(DownloadOutcome):
    pass


class DownloadFailed(DownloadOutcome):
    pass


class DownloadCancelled(DownloadOutcome):
    pass


def classify_unexpected(exc: Exception) -> DownloadFailed | DownloadSkipped:
    if isinstance(exc, FileExistsError):
        return DownloadSkipped("already_exists", "The destination file already exists.", "preflight", retryable=False, technical_detail=type(exc).__name__)
    if isinstance(exc, PermissionError):
        return DownloadFailed("filesystem_permission_denied", "Harmony cannot write to the music library.", "filesystem", retryable=False, technical_detail=type(exc).__name__)
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return DownloadFailed("disk_full", "The destination disk is full.", "filesystem", retryable=False, technical_detail=type(exc).__name__)
    if isinstance(exc, TimeoutError):
        return DownloadFailed("download_timeout", "The download timed out.", "download", retryable=True, technical_detail=type(exc).__name__)
    return DownloadFailed("unexpected_error", "The download could not be completed.", "download", retryable=True, technical_detail=type(exc).__name__)
