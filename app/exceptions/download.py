class DownloadError(Exception):
    """Base exception for download-related errors."""


class TrackAlreadyExistsError(DownloadError):
    """Raised when a track already exists in the local library."""


class ActiveDownloadExistsError(DownloadError):
    """Raised when an active download job already exists."""