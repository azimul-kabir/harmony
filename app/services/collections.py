from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.database.models import Song
from app.services.library_filters import (
    LibraryFilters,
    apply_song_filters,
    apply_song_sort,
)


RuleOperator = Literal[
    "equals",
    "not_equals",
    "within_days",
    "missing",
    "maximum",
    "album_song_count_gte",
    "placeholder",
]


@dataclass(frozen=True, slots=True)
class CollectionRule:
    field: str
    operator: RuleOperator
    value: object | None = None

    def to_dict(self) -> dict:
        return {"field": self.field, "operator": self.operator, "value": self.value}


@dataclass(frozen=True, slots=True)
class RuleGroup:
    match: Literal["all", "any"]
    rules: tuple[CollectionRule | "RuleGroup", ...]

    def to_dict(self) -> dict:
        return {
            "match": self.match,
            "rules": [rule.to_dict() for rule in self.rules],
        }


@dataclass(frozen=True, slots=True)
class CollectionDefinition:
    id: str
    name: str
    description: str
    tone: str
    icon: str
    rule: CollectionRule | RuleGroup
    placeholder: bool = False

    def to_dict(self, *, song_count: int | None = None) -> dict:
        result = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tone": self.tone,
            "icon": self.icon,
            "rule": self.rule.to_dict(),
            "placeholder": self.placeholder,
        }
        if song_count is not None:
            result["song_count"] = song_count
        return result


COLLECTIONS = (
    CollectionDefinition(
        "recently-added",
        "Recently Added",
        "Music added to the Library Index during the last seven days.",
        "blue",
        "recent",
        CollectionRule("created_at", "within_days", 7),
    ),
    CollectionDefinition(
        "recently-downloaded",
        "Recently Downloaded",
        "Downloads added during the last seven days.",
        "cyan",
        "download",
        RuleGroup(
            "all",
            (
                CollectionRule("created_at", "within_days", 7),
                CollectionRule("download_source", "not_equals", "filesystem"),
            ),
        ),
    ),
    CollectionDefinition(
        "highest-bitrate",
        "Highest Bitrate",
        "Tracks at the highest bitrate currently in the Library.",
        "violet",
        "quality",
        CollectionRule("bitrate", "maximum"),
    ),
    CollectionDefinition(
        "missing-artwork",
        "Missing Artwork",
        "Tracks that still need a local artwork resource.",
        "amber",
        "artwork",
        CollectionRule("artwork_status", "equals", "missing"),
    ),
    CollectionDefinition(
        "missing-metadata",
        "Missing Metadata",
        "Tracks missing a title, artist, or album.",
        "rose",
        "metadata",
        RuleGroup(
            "any",
            (
                CollectionRule("title", "missing"),
                CollectionRule("artist", "missing"),
                CollectionRule("album", "missing"),
            ),
        ),
    ),
    CollectionDefinition(
        "recently-modified",
        "Recently Modified",
        "Files modified during the last seven days.",
        "green",
        "modified",
        CollectionRule("last_modified", "within_days", 7),
    ),
    CollectionDefinition(
        "large-albums",
        "Large Albums",
        "Tracks from albums containing at least ten indexed songs.",
        "indigo",
        "album",
        CollectionRule("album", "album_song_count_gte", 10),
    ),
    CollectionDefinition(
        "favorites",
        "Favorites",
        "Ready for a future favorites signal.",
        "pink",
        "favorite",
        CollectionRule("favorite", "placeholder"),
        placeholder=True,
    ),
)


class CollectionEngine:
    """Compiles registered collection rules into live Library Index queries."""

    def __init__(self, definitions=COLLECTIONS):
        self._definitions = {definition.id: definition for definition in definitions}

    def definitions(self) -> tuple[CollectionDefinition, ...]:
        return tuple(self._definitions.values())

    def get(self, collection_id: str) -> CollectionDefinition | None:
        return self._definitions.get(collection_id)

    def statement(
        self,
        collection_id: str,
        *,
        filters: LibraryFilters | None = None,
        sort_by: str = "artist",
    ):
        definition = self.get(collection_id)
        if definition is None:
            raise KeyError(collection_id)
        statement = select(Song).where(
            Song.availability_status == "available",
            self._compile(definition.rule),
        )
        statement = apply_song_filters(statement, filters or LibraryFilters())
        return apply_song_sort(statement, sort_by)

    def count(self, db: Session, collection_id: str) -> int:
        statement = self.statement(collection_id).order_by(None).subquery()
        return db.scalar(select(func.count()).select_from(statement)) or 0

    def summaries(self, db: Session) -> list[dict]:
        return [
            definition.to_dict(song_count=self.count(db, definition.id))
            for definition in self.definitions()
        ]

    def _compile(self, rule: CollectionRule | RuleGroup):
        if isinstance(rule, RuleGroup):
            expressions = [self._compile(child) for child in rule.rules]
            return or_(*expressions) if rule.match == "any" else and_(*expressions)

        if rule.operator == "placeholder":
            return false()
        column = getattr(Song, rule.field)
        if rule.operator == "equals":
            return column == rule.value
        if rule.operator == "not_equals":
            return column != rule.value
        if rule.operator == "missing":
            return or_(column.is_(None), column == "")
        if rule.operator == "within_days":
            cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=int(rule.value))
            return column >= cutoff
        if rule.operator == "maximum":
            candidate = aliased(Song)
            maximum = select(func.max(getattr(candidate, rule.field))).where(
                candidate.availability_status == "available"
            ).scalar_subquery()
            return column == maximum
        if rule.operator == "album_song_count_gte":
            album_song = aliased(Song)
            album_artist = func.coalesce(album_song.album_artist, album_song.artist, "")
            song_artist = func.coalesce(Song.album_artist, Song.artist, "")
            count = (
                select(func.count(album_song.id))
                .where(
                    album_song.availability_status == "available",
                    album_song.album == Song.album,
                    album_artist == song_artist,
                )
                .correlate(Song)
                .scalar_subquery()
            )
            return count >= int(rule.value)
        raise ValueError(f"Unsupported collection rule operator: {rule.operator}")


collection_engine = CollectionEngine()
