"""Database connection.

The engine is SQLAlchemy's connection manager. It keeps a pool of open
connections to Postgres so each request doesn't have to open a new one.
"""

import os
from functools import lru_cache

from sqlalchemy import Engine, create_engine


def database_url() -> str:
    """Read DATABASE_URL from the environment and point it at the psycopg driver."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env, or export it.")
    # .env.example uses plain "postgresql://". SQLAlchemy would then look for
    # the older psycopg2 driver, so tell it to use psycopg (version 3) instead.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


@lru_cache
def get_engine() -> Engine:
    """Create the engine once and reuse it for every request.

    lru_cache makes this run only on the first call. The engine is created
    lazily (not at import time), so the app can start and answer /health
    with a 503 even if DATABASE_URL points at a database that's down.
    """
    return create_engine(
        database_url(),
        pool_pre_ping=True,  # test a pooled connection before using it, in case Postgres restarted
        connect_args={"connect_timeout": 3},  # give up after 3 seconds instead of hanging
    )
