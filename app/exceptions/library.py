class LibraryError(Exception):
    """Base exception for library operations."""


class DuplicateTrackError(LibraryError):
    """Track already exists in the library."""

    def __init__(self, message: str, *, existing_path=None):
        super().__init__(message)
        self.existing_path = existing_path


class MetadataReadError(LibraryError):
    """Unable to read metadata from an audio file."""


class ImportError(LibraryError):
    """Failed to import a track into the library."""
