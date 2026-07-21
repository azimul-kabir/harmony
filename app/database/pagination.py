"""Memory-bounded keyset iteration helpers for background services."""

from collections.abc import Iterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session


def iter_primary_keys(
    db: Session,
    model: Any,
    *,
    batch_size: int = 1000,
) -> Iterator[int]:
    """Yield integer primary keys without materializing an entire table."""
    primary_key = model.id
    last_id = 0
    while True:
        batch = tuple(db.scalars(
            select(primary_key)
            .where(primary_key > last_id)
            .order_by(primary_key)
            .limit(batch_size)
        ))
        if not batch:
            return
        yield from batch
        last_id = batch[-1]
