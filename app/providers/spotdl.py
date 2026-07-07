from app.providers.base import MetadataProvider


class SpotDLProvider(MetadataProvider):

    def playlist(self, url: str):
        raise NotImplementedError

    def album(self, url: str):
        raise NotImplementedError

    def artist(self, url: str):
        raise NotImplementedError

    def track(self, url: str):
        raise NotImplementedError