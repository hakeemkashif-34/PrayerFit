"""Tests for the /health endpoint."""

from fastapi.testclient import TestClient

from app.main import app

# TestClient calls the app directly in memory, so no server or database is needed.
client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
