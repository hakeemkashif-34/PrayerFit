"""Settings for Google sign-in and sessions, read from the environment.

These are only read when a Google endpoint is used, so /health and
/prayer-times still work on a machine with no Google keys.
"""

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    token_encryption_key: str
    # Where the app is served from. POSTs from any other origin are refused.
    app_origin: str
    cookie_secure: bool
    session_days: int


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set. Copy .env.example to .env and fill it in.")
    return value


@lru_cache
def get_settings() -> Settings:
    return Settings(
        google_client_id=_required("GOOGLE_CLIENT_ID"),
        google_client_secret=_required("GOOGLE_CLIENT_SECRET"),
        google_redirect_uri=os.environ.get(
            "GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback"
        ),
        token_encryption_key=_required("TOKEN_ENCRYPTION_KEY"),
        app_origin=os.environ.get("APP_ORIGIN", "http://localhost:8000").rstrip("/"),
        cookie_secure=os.environ.get("COOKIE_SECURE", "true").lower() != "false",
        session_days=int(os.environ.get("SESSION_DAYS", "30")),
    )
