from app.providers.youtube_music import YouTubeMusicSource

_SOURCES = {"youtube_music": YouTubeMusicSource()}

def get_source(identifier: str):
    try: return _SOURCES[identifier]
    except KeyError as exc: raise ValueError("Unsupported download source.") from exc

def detect_source(url: str):
    for source in _SOURCES.values():
        if source.detect_url(url): return source
    return None
