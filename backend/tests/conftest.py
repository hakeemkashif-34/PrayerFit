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

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import get_engine  # noqa: E402
from app.models import Base  # noqa: E402


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
