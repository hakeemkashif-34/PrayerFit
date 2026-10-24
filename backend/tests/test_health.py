"""Tests for the /health endpoint.

These need a real Postgres running, with DATABASE_URL pointing at it.
See the README for how to start one.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.db import get_engine
from app.main import app

# TestClient calls the app directly in memory, so no web server is needed.
client = TestClient(app)


@pytest.fixture
def database_down():
    """Make /health use an engine pointing at a database that isn't there.

    Port 1 on this machine has nothing listening, so the connection is
    refused straight away. dependency_overrides tells FastAPI to call our
    function instead of get_engine, only for this test.
    """
    dead_engine = create_engine(
        "postgresql+psycopg://nobody:nothing@127.0.0.1:1/nothing",
        connect_args={"connect_timeout": 3},
    )
    app.dependency_overrides[get_engine] = lambda: dead_engine
    yield
    # Undo the swap so other tests use the real database again.
    app.dependency_overrides.clear()
    dead_engine.dispose()


def test_health_ok_when_database_is_up():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_503_when_database_is_down(database_down):
    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "unreachable"}
