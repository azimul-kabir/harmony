class LibraryError(Exception):
    """Base exception for library operations."""


class DuplicateTrackError(LibraryError):
    """Track already exists in the library."""


class MetadataReadError(LibraryError):
    """Unable to read metadata from an audio file."""


class ImportError(LibraryError):
    """Failed to import a track into the library."""
