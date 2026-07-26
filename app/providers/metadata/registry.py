from app.providers.metadata.base import MetadataProvider
from app.providers.metadata.musicbrainz import MusicBrainzProvider
from app.providers.metadata.spotify import SpotifyMetadataProvider

_providers: dict[str, MetadataProvider] = {}


def get_provider(name: str) -> MetadataProvider:
    factories = {
        "musicbrainz": MusicBrainzProvider,
        "spotify": SpotifyMetadataProvider,
    }
    if name not in factories:
        raise KeyError(name)
    if name not in _providers:
        _providers[name] = factories[name]()
    return _providers[name]


def all_providers() -> dict[str, MetadataProvider]:
    get_provider("musicbrainz")
    get_provider("spotify")
    return dict(_providers)


async def close_providers() -> None:
    providers = list(_providers.values())
    _providers.clear()
    for provider in providers:
        await provider.close()
