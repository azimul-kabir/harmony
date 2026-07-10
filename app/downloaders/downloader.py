from abc import ABC, abstractmethod
from pathlib import Path

from app.domain.track import Track


class Downloader(ABC):
    @abstractmethod
    def download(self, track: Track) -> Path:
        """Download a track and return the downloaded file path."""
        raise NotImplementedError
