from dataclasses import dataclass, field


@dataclass(slots=True)
class Track:
    # Basic
    title: str | None = None
    artist: str | None = None

    # Album
    album: str | None = None
    album_artist: str | None = None

    # Track info
    track: int | None = None
    disc: int | None = None

    year: int | None = None
    genre: str | None = None
    duration: float | None = None

    # Multiple artists
    artists: list[str] = field(default_factory=list)
    # Artist IDs are retained from Spotify's track payload for provider metadata.
    spotify_artist_ids: list[str] = field(default_factory=list)
    genre_provenance: str | None = None

    # Artwork
    cover_url: str | None = None

    # External identifiers
    spotify_track_id: str | None = None
    spotify_album_id: str | None = None
    spotify_url: str | None = None
    isrc: str | None = None
    # Download-source identity is deliberately provider neutral.  The Spotify
    # fields above remain for compatibility with existing libraries.
    source_provider: str = "spotify"
    source_item_id: str | None = None
    source_url: str | None = None

    # Local library
    path: str | None = None
