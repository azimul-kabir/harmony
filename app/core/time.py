"""Consistent timestamp helpers for SQLite-backed domain services."""

from datetime import UTC, datetime


def utcnow_naive() -> datetime:
    """Return UTC without tzinfo, matching Harmony's existing DateTime columns."""
    return datetime.now(UTC).replace(tzinfo=None)
