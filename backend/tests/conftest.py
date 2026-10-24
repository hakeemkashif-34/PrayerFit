"""Shared test setup.

The db fixture is only used by tests that need Postgres. The prayer time
tests don't ask for it, so they still run without a database.
"""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.db import get_engine
from app.models import Base


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
