from app.providers.metadata.base import MetadataProvider
from app.providers.metadata.musicbrainz import MusicBrainzProvider

_providers: dict[str, MetadataProvider] = {}


def get_provider(name: str) -> MetadataProvider:
    if name != "musicbrainz":
        raise KeyError(name)
    if name not in _providers:
        _providers[name] = MusicBrainzProvider()
    return _providers[name]


def all_providers() -> dict[str, MetadataProvider]:
    get_provider("musicbrainz")
    return dict(_providers)


async def close_providers() -> None:
    providers = list(_providers.values())
    _providers.clear()
    for provider in providers:
        await provider.close()
