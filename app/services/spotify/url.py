from urllib.parse import urlparse


def spotify_resource(url: str) -> tuple[str, str]:
    """
    Returns:
        ("track", id)
        ("album", id)
        ("playlist", id)
    """

    path = urlparse(url).path.strip("/")

    parts = path.split("/")

    if len(parts) < 2:
        raise ValueError("Invalid Spotify URL.")

    return parts[0], parts[1]
