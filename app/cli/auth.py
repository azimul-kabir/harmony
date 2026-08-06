"""Reset an administrator password from the trusted host/container.

Usage: python -m app.cli.auth reset-password ADMIN
The new password is read from HARMONY_RECOVERY_PASSWORD_FILE.
"""
import argparse
import os
from pathlib import Path

from sqlalchemy import select, update

from app.core.time import utcnow_naive
from app.database.init_db import init_db
from app.database.models import AuthSession, User
from app.database.session import SessionLocal
from app.web.auth import PASSWORD_HASHER, PASSWORD_MIN_LENGTH, normalize_username


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["reset-password"])
    parser.add_argument("username")
    args = parser.parse_args()
    filename = os.environ.get("HARMONY_RECOVERY_PASSWORD_FILE", "")
    if not filename:
        raise SystemExit("Set HARMONY_RECOVERY_PASSWORD_FILE to a host-only secret file")
    try:
        password = Path(filename).read_text(encoding="utf-8").rstrip("\r\n")
    except OSError as exc:
        raise SystemExit("Recovery password file cannot be read") from exc
    if len(password) < PASSWORD_MIN_LENGTH:
        raise SystemExit(f"New password must be at least {PASSWORD_MIN_LENGTH} characters")
    init_db(); db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.username == normalize_username(args.username)))
        if not user or not user.is_admin:
            raise SystemExit("Administrator not found")
        user.password_hash = PASSWORD_HASHER.hash(password)
        user.session_version += 1; user.updated_at = utcnow_naive()
        db.execute(update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
                   .values(revoked_at=utcnow_naive()))
        db.commit()
    finally:
        db.close()
    print("Administrator password reset; all of that user's sessions were revoked.")


if __name__ == "__main__":
    main()
