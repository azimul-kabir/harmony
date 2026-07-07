from abc import ABC, abstractmethod

from app.domain.track import Track


class MetadataProvider(ABC):
    @abstractmethod
    def playlist(self, url: str) -> list[Track]:
        """Return all tracks from a playlist."""
        raise NotImplementedError

    @abstractmethod
    def album(self, url: str) -> list[Track]:
        """Return all tracks from an album."""
        raise NotImplementedError

    @abstractmethod
    def artist(self, url: str) -> list[Track]:
        """Return all tracks from an artist."""
        raise NotImplementedError

    @abstractmethod
    def track(self, url: str) -> Track:
        """Return a single track."""
        raise NotImplementedError