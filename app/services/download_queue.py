from app.domain.comparison import PlaylistComparison, TrackStatus
from app.domain.download import DownloadItem, DownloadQueue


def build_download_queue(
    comparison: PlaylistComparison,
) -> DownloadQueue:
    items = [
        DownloadItem(track=item.track)
        for item in comparison.tracks
        if item.status == TrackStatus.MISSING
    ]

    return DownloadQueue(items=items)