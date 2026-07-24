"""Run one safe artist-genre credential diagnostic: python -m ... ARTIST_ID."""
from __future__ import annotations
import sys
from app.services.spotify.genres import GenreFailureCategory, _fetch_artists

def main() -> int:
    artist_id = sys.argv[1] if len(sys.argv) == 2 else ""
    result = _fetch_artists([artist_id], job_id=None)
    error = result.error
    disabled = error is not None and error.category == GenreFailureCategory.DISABLED
    print(f"enabled={'false' if disabled else 'true'}")
    print(f"authenticated={'false' if disabled or error and error.category in (GenreFailureCategory.UNAUTHORIZED, GenreFailureCategory.CREDENTIALS_MISSING) else 'true'}")
    print(f"artist_request_success={'true' if error is None else 'false'}")
    print(f"http_status={error.http_status if error and error.http_status is not None else 'none'}")
    print(f"failure_category={error.category if error else 'none'}")
    print(f"returned_genre_count={len(result.artists.get(artist_id, []))}")
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
