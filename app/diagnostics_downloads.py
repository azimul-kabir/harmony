"""Aggregate-only Downloads diagnostic.

Run ``python -m app.diagnostics_downloads`` in the Harmony container.  This is
safe to share because it intentionally prints no titles, paths, URLs, or errors.
"""

import json

from app.database.session import SessionLocal
from app.services.download_dashboard import download_diagnostics


def main() -> None:
    db = SessionLocal()
    try:
        print(json.dumps(download_diagnostics(db), sort_keys=True))
    finally:
        db.close()


if __name__ == "__main__":
    main()
