"""Rules every set of prayer times has to follow, checked every day of the year."""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.prayer_times import (
    AsrMethod,
    CalculationMethod,
    calculate_prayer_times,
    round_down_to_minute,
    round_up_to_minute,
)
from tests.places import ALL_PLACES, OTTAWA, ST_JOHNS, days_in, place_id

YEAR = 2026


def utc(moment: datetime) -> datetime:
    # Compare in UTC. Python compares two times in the same zone by wall clock,
    # which is wrong across a daylight saving change.
    return moment.astimezone(timezone.utc)


def calculate(place, day, method=CalculationMethod.ISNA, asr_method=AsrMethod.STANDARD):
    return calculate_prayer_times(
        place.latitude, place.longitude, day, place.timezone, method, asr_method
    )


@pytest.mark.parametrize(
    "exact, expected",
    [
        ("12:00:00", "12:00"),
        ("12:00:00.000001", "12:01"),
        ("12:00:01", "12:01"),
        ("12:00:59", "12:01"),
        ("23:59:30", "00:00"),  # rolls over to the next day
    ],
)
def test_round_up_to_minute(exact, expected):
    moment = datetime.fromisoformat(f"2026-01-01T{exact}+00:00")
    assert round_up_to_minute(moment).strftime("%H:%M") == expected


@pytest.mark.parametrize(
    "exact, expected",
    [("05:59:59", "05:59"), ("06:00:00", "06:00"), ("06:00:30", "06:00")],
)
def test_round_down_to_minute(exact, expected):
    moment = datetime.fromisoformat(f"2026-01-01T{exact}+00:00")
    assert round_down_to_minute(moment).strftime("%H:%M") == expected


# St. John's is 3.5 hours behind UTC, so this also checks rounding in a half hour zone.
@pytest.mark.parametrize("place", [OTTAWA, ST_JOHNS], ids=place_id)
def test_start_times_round_up_and_sunrise_rounds_down(place):
    for day in days_in(YEAR):
        for name, prayer in calculate(place, day).in_order():
            shown, exact = utc(prayer.time), prayer.exact_time
            assert shown.second == 0 and shown.microsecond == 0
            if name == "sunrise":
                # Sunrise ends Fajr, so showing it a little early is the safe side.
                assert timedelta(0) <= exact - shown < timedelta(minutes=1), f"{day} {name}"
            else:
                # Never show a prayer before it starts.
                assert timedelta(0) <= shown - exact < timedelta(minutes=1), f"{day} {name}"


@pytest.mark.parametrize("asr_method", list(AsrMethod))
@pytest.mark.parametrize("method", list(CalculationMethod))
def test_every_time_says_where_it_came_from(method, asr_method):
    times = calculate(OTTAWA, date(2026, 10, 24), method, asr_method)
    assert times.method == method
    assert times.asr_method == asr_method
    for name, prayer in times.in_order():
        assert prayer.source == "calculated", name
        assert prayer.method == method, name
        assert prayer.asr_method == asr_method, name


@pytest.mark.parametrize("method", list(CalculationMethod))
@pytest.mark.parametrize("place", ALL_PLACES, ids=place_id)
def test_times_are_in_order(place, method):
    previous_isha = None
    for day in days_in(YEAR):
        times = calculate(place, day, method)
        moments = [utc(prayer.time) for _, prayer in times.in_order()]
        # Fajr < Sunrise < Dhuhr < Asr < Maghrib < Isha
        assert moments == sorted(moments) and len(set(moments)) == 6, f"{day}: {moments}"
        # Isha never runs into the next day's Fajr.
        if previous_isha is not None:
            assert previous_isha <= moments[0], f"{day}: Isha before was {previous_isha}"
        previous_isha = moments[-1]


@pytest.mark.parametrize("place", ALL_PLACES, ids=place_id)
def test_hanafi_asr_is_always_later(place):
    for day in days_in(YEAR):
        standard = calculate(place, day, asr_method=AsrMethod.STANDARD).asr
        hanafi = calculate(place, day, asr_method=AsrMethod.HANAFI).asr
        assert utc(hanafi.time) > utc(standard.time), day
