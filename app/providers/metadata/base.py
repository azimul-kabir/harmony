from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from app.domain.metadata.provider import CandidatePage, ProviderCandidate

EntityType = Literal["recording", "release", "release_group", "artist"]
SearchType = Literal["recording", "release", "artist"]
ProgressCallback = Callable[[int, int | None], None]


@dataclass(frozen=True)
class ProviderCapabilities:
    provider: str
    search: tuple[SearchType, ...]
    lookup: tuple[EntityType, ...]
    pagination: bool
    relationships: bool
    forced_refresh: bool
    cache_bypass: bool


class MetadataProvider(ABC):
    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities: ...

    @abstractmethod
    async def search(self, entity_type: SearchType, query: str, *, limit: int = 25,
                     offset: int = 0, force_refresh: bool = False, bypass_cache: bool = False,
                     cancel_event: asyncio.Event | None = None,
                     progress: ProgressCallback | None = None) -> CandidatePage: ...

    @abstractmethod
    async def lookup(self, entity_type: EntityType, entity_id: str, *,
                     force_refresh: bool = False, bypass_cache: bool = False,
                     cancel_event: asyncio.Event | None = None,
                     progress: ProgressCallback | None = None) -> ProviderCandidate: ...

    @abstractmethod
    def status(self) -> dict: ...

    @abstractmethod
    async def close(self) -> None: ...
