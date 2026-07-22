"""Run one safe artist-genre credential diagnostic: python -m ... ARTIST_ID."""
from __future__ import annotations
import sys
from app.services.spotify.genres import _fetch_artists

def main() -> int:
    artist_id = sys.argv[1] if len(sys.argv) == 2 else ""
    result = _fetch_artists([artist_id], job_id=None)
    error = result.error
    print(f"authenticated={'false' if error and error.category == 'unauthorized' else 'true'}")
    print(f"artist_request_success={'true' if error is None else 'false'}")
    print(f"http_status={error.http_status if error else 'none'}")
    print(f"failure_category={error.category if error else 'none'}")
    print(f"returned_genre_count={len(result.artists.get(artist_id, []))}")
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
