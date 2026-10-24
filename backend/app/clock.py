"""The current time, as a dependency, so tests can pick "today"."""

from datetime import UTC, datetime


def get_now() -> datetime:
    return datetime.now(UTC)
