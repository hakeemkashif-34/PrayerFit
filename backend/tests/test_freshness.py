"""Masjid times are used for 24 hours after a good fetch. After that, calculated times are used."""

from datetime import UTC, datetime, timedelta

from app.masjid_times.freshness import Freshness, freshness

NOW = datetime(2026, 10, 25, 16, 0, tzinfo=UTC)


def test_fresh_under_24_hours():
    assert freshness(NOW - timedelta(hours=23, minutes=59), NOW) is Freshness.FRESH
    assert freshness(NOW, NOW).usable


def test_not_used_from_24_hours():
    assert freshness(NOW - timedelta(hours=24), NOW) is Freshness.STALE
    assert not freshness(NOW - timedelta(hours=24), NOW).usable
    assert not freshness(NOW - timedelta(days=30), NOW).usable


def test_never_fetched():
    assert freshness(None, NOW) is Freshness.NEVER
    assert not Freshness.NEVER.usable
