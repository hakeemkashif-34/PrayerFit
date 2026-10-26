"""Masjid times are fresh for 24 hours, stale (still used) up to 7 days, then not used."""

from datetime import UTC, datetime, timedelta

from app.masjid_times.freshness import Freshness, freshness

NOW = datetime(2026, 10, 25, 16, 0, tzinfo=UTC)


def test_fresh_under_24_hours():
    assert freshness(NOW - timedelta(hours=23, minutes=59), NOW) is Freshness.FRESH
    assert freshness(NOW, NOW).usable


def test_stale_from_24_hours_to_7_days():
    assert freshness(NOW - timedelta(hours=24), NOW) is Freshness.STALE
    assert freshness(NOW - timedelta(days=7), NOW) is Freshness.STALE
    assert freshness(NOW - timedelta(days=7), NOW).usable


def test_too_old_after_7_days():
    assert freshness(NOW - timedelta(days=7, seconds=1), NOW) is Freshness.TOO_OLD
    assert not freshness(NOW - timedelta(days=30), NOW).usable


def test_never_fetched():
    assert freshness(None, NOW) is Freshness.NEVER
    assert not Freshness.NEVER.usable
