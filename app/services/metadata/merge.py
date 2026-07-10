from app.domain.metadata.track import TrackMetadata


def merge_metadata(
    *tracks: TrackMetadata,
) -> TrackMetadata:
    raise NotImplementedError