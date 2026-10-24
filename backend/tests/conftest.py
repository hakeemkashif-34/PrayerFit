"""Shared test setup.

The db fixture is only used by tests that need Postgres. The prayer time
tests don't ask for it, so they still run without a database.
"""

import os

from cryptography.fernet import Fernet

# Fake settings, set before the app reads them. These override any real
# values in the environment, so the tests never use real Google keys.
os.environ["GOOGLE_CLIENT_ID"] = "test-client-id.apps.googleusercontent.com"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-client-secret"
os.environ["GOOGLE_REDIRECT_URI"] = "http://testserver/auth/google/callback"
# A new key every run, so nothing depends on a key saved somewhere.
os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
# TestClient sends requests to http://testserver.
os.environ["APP_ORIGIN"] = "http://testserver"
# The test client uses plain http, and won't send Secure cookies over it.
os.environ["COOKIE_SECURE"] = "false"

from datetime import datetime, time  # noqa: E402
from urllib.parse import parse_qs, urlparse  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.clock import get_now  # noqa: E402
from app.db import get_engine  # noqa: E402
from app.google_http import get_google_http  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from tests.fake_google import FakeGoogle  # noqa: E402


@pytest.fixture(scope="session")
def migrated_engine():
    """Run the real migrations once per test run, the same way Docker does."""
    config = Config("alembic.ini")
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")
    return get_engine()


@pytest.fixture
def db(migrated_engine):
    """Start every test with empty tables, so tests can't affect each other."""
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    with migrated_engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} CASCADE"))
    return migrated_engine


@pytest.fixture
def fake_google():
    """Point every Google call the app makes at a fresh fake Google."""
    fake = FakeGoogle()

    def fake_http():
        with fake.client() as client:
            yield client

    app.dependency_overrides[get_google_http] = fake_http
    yield fake
    app.dependency_overrides.pop(get_google_http, None)


def new_client() -> TestClient:
    """A browser of its own, with its own cookies, on this app's origin."""
    return TestClient(app, headers={"Origin": "http://testserver"}, follow_redirects=False)


@pytest.fixture
def client(db, fake_google):
    with new_client() as test_client:
        yield test_client


def start_sign_in(client: TestClient) -> dict[str, str]:
    """Open /auth/google/login and return the query Google would receive."""
    response = client.get("/auth/google/login")
    assert response.status_code == 307
    return {k: v[0] for k, v in parse_qs(urlparse(response.headers["location"]).query).items()}


def sign_in(client: TestClient, fake: FakeGoogle, sub: str = "user-a", email: str = "a@example.com", **code_options):
    """Go through the whole sign-in, as if the user clicked Allow on Google."""
    google_query = start_sign_in(client)
    code = fake.issue_code(sub, email, google_query["code_challenge"], **code_options)
    response = client.get(
        "/auth/google/callback", params={"code": code, "state": google_query["state"]}
    )
    assert response.status_code == 303, response.text
    return response


@pytest.fixture
def set_today():
    """Pretend it's noon on a given day in a given time zone."""

    def set_day(day, time_zone="America/Toronto"):
        moment = datetime.combine(day, time(12), tzinfo=ZoneInfo(time_zone))
        app.dependency_overrides[get_now] = lambda: moment

    yield set_day
    app.dependency_overrides.pop(get_now, None)
