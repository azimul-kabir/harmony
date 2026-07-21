"""Canonical SQL predicates shared by Library queries and health checks."""

from sqlalchemy import or_

from app.database.models import Song


def missing_metadata_expression():
    """Return the canonical definition of incomplete core track metadata."""
    return or_(
        Song.title.is_(None),
        Song.title == "",
        Song.artist.is_(None),
        Song.artist == "",
        Song.album.is_(None),
        Song.album == "",
    )


def available_expression():
    """Return the canonical predicate for files currently available to clients."""
    return Song.availability_status == "available"
