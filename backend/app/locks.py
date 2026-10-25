"""Postgres advisory locks: "only one of these at a time", across every process.

An advisory lock is a lock on a number, not on a table row. It's held on
its own connection, so commits in between don't release it.
"""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session


def lock_key(name: str) -> int:
    """Turn a name like "calendar:<user id>" into the 64-bit number Postgres locks on."""
    return int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big", signed=True)


@contextmanager
def advisory_lock(db: Session, name: str) -> Iterator[None]:
    """Wait until no one else holds the lock for `name`, then hold it until the block ends."""
    key = lock_key(name)
    with db.get_bind().connect() as lock_connection:
        lock_connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": key})
        try:
            yield
        finally:
            lock_connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
            lock_connection.commit()
