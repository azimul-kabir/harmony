from app.downloaders.spotdl import SpotDLClient

client = SpotDLClient()


def import_playlist(url: str):
    return client.playlist(url)