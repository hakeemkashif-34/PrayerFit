"""Settings read from the environment.

Google settings are only read when a Google endpoint is used, so /health
and /prayer-times still work on a machine with no Google keys.
"""

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class GoogleSettings:
    client_id: str
    client_secret: str
    redirect_uri: str
    # Fernet key used to encrypt Google tokens before they're saved.
    token_encryption_key: str


@dataclass(frozen=True)
class AppSettings:
    # Where the app is served from. POSTs from any other origin are refused.
    origin: str
    cookie_secure: bool
    session_days: int


def _optional(name: str, default: str) -> str:
    # Docker Compose passes a missing .env value as "", so treat "" as missing.
    return os.environ.get(name) or default


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set. Copy .env.example to .env and fill it in.")
    return value


@dataclass(frozen=True)
class OsmSettings:
    """Photon, a free search built on OpenStreetMap data. It asks apps to say who they are."""

    contact_email: str
    photon_url: str

    @property
    def user_agent(self) -> str:
        # A stock library User-Agent doesn't say who to contact.
        return f"MuslimCalendar/0.4 (+mailto:{self.contact_email})"


@lru_cache
def get_osm_settings() -> OsmSettings:
    return OsmSettings(
        contact_email=_required("OSM_CONTACT_EMAIL"),
        photon_url=_optional("PHOTON_URL", "https://photon.komoot.io").rstrip("/"),
    )


@lru_cache
def get_google_settings() -> GoogleSettings:
    return GoogleSettings(
        client_id=_required("GOOGLE_CLIENT_ID"),
        client_secret=_required("GOOGLE_CLIENT_SECRET"),
        redirect_uri=_optional("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback"),
        token_encryption_key=_required("TOKEN_ENCRYPTION_KEY"),
    )


@lru_cache
def get_app_settings() -> AppSettings:
    return AppSettings(
        origin=_optional("APP_ORIGIN", "http://localhost:8000").rstrip("/"),
        cookie_secure=_optional("COOKIE_SECURE", "true").lower() != "false",
        session_days=int(_optional("SESSION_DAYS", "30")),
    )
