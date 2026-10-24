"""High latitude rules: what happens when it never gets dark enough.

In June in Edmonton the sun only goes about 13 degrees below the horizon, so it
never reaches the 15 degrees ISNA uses for Fajr and Isha. Instead of an error,
the app uses a share of the night:

1. Below 48 degrees: Fajr no earlier, and Isha no later, than the middle of the night.
2. From 48 degrees: Fajr no earlier than the last seventh of the night, and Isha
   no later than the first seventh.
3. Above 65 degrees: some days have no sunrise or sunset at all, so use the
   times at 65 degrees.

"The night" is sunset to sunrise. Fajr uses the night that it ends, and Isha uses
the night that it starts.
"""

from datetime import date, timedelta

import pytest

from app.prayer_times import CalculationMethod, HighLatitudeRule, calculate_prayer_times
from app.prayer_times.astronomy import SUNRISE_ALTITUDE, SolarDay
from tests.places import EDMONTON, INUVIK, MCMURDO, MECCA, OTTAWA, ST_JOHNS, days_in, place_id

SUMMER_SOLSTICE = date(2026, 6, 21)
WINTER_SOLSTICE = date(2026, 12, 21)
# The exact times are floats turned into datetimes, so allow for tiny rounding.
TINY = timedelta(milliseconds=1)


def calculate(place, day, method=CalculationMethod.ISNA):
    return calculate_prayer_times(place.latitude, place.longitude, day, place.timezone, method)


def sun_reaches(place, day, angle):
    """Does the sun get this many degrees below the horizon tonight?"""
    sun = SolarDay(day, place.latitude, place.longitude)
    return sun.time_at_altitude(-angle, after_noon=True) is not None


def test_edmonton_summer_uses_seventh_of_the_night():
    day = SUMMER_SOLSTICE
    assert not sun_reaches(EDMONTON, day, 15)

    yesterday = calculate(EDMONTON, day - timedelta(days=1))
    today = calculate(EDMONTON, day)
    tomorrow = calculate(EDMONTON, day + timedelta(days=1))

    assert today.fajr.high_latitude_rule == HighLatitudeRule.SEVENTH_OF_THE_NIGHT
    assert today.isha.high_latitude_rule == HighLatitudeRule.SEVENTH_OF_THE_NIGHT

    # Fajr: the last seventh of last night (yesterday's sunset to this sunrise).
    sunrise = today.sunrise.exact_time
    last_night = sunrise - yesterday.maghrib.exact_time
    assert abs(today.fajr.exact_time - (sunrise - last_night / 7)) < TINY

    # Isha: the first seventh of tonight (this sunset to tomorrow's sunrise).
    sunset = today.maghrib.exact_time
    tonight = tomorrow.sunrise.exact_time - sunset
    assert abs(today.isha.exact_time - (sunset + tonight / 7)) < TINY


def test_below_48_degrees_uses_middle_of_the_night():
    # St. John's is at 47.6 degrees. In June the sun gets about 19 degrees down,
    # not quite the 19.5 the Egyptian method needs for Fajr.
    day = SUMMER_SOLSTICE
    assert not sun_reaches(ST_JOHNS, day, 19.5)

    yesterday = calculate(ST_JOHNS, day - timedelta(days=1), CalculationMethod.EGYPTIAN)
    today = calculate(ST_JOHNS, day, CalculationMethod.EGYPTIAN)

    assert today.fajr.high_latitude_rule == HighLatitudeRule.MIDDLE_OF_THE_NIGHT
    sunrise = today.sunrise.exact_time
    last_night = sunrise - yesterday.maghrib.exact_time
    assert abs(today.fajr.exact_time - (sunrise - last_night / 2)) < TINY


@pytest.mark.parametrize("place", [OTTAWA, MECCA], ids=place_id)
@pytest.mark.parametrize("method", list(CalculationMethod))
def test_no_rule_where_it_always_gets_dark_enough(place, method):
    """The rules must never change normal times."""
    for day in days_in(2026):
        for name, prayer in calculate(place, day, method).in_order():
            assert prayer.high_latitude_rule is None, f"{day} {name}"


@pytest.mark.parametrize(
    "day", [SUMMER_SOLSTICE, WINTER_SOLSTICE], ids=["midnight sun", "polar night"]
)
def test_above_65_degrees_uses_the_times_at_65(day):
    # Inuvik is at 68.4 degrees. The sun doesn't set on June 21 or rise on December 21.
    sun = SolarDay(day, INUVIK.latitude, INUVIK.longitude)
    assert sun.time_at_altitude(SUNRISE_ALTITUDE, after_noon=True) is None

    times = calculate(INUVIK, day)
    at_65 = calculate_prayer_times(65, INUVIK.longitude, day, INUVIK.timezone)

    for (name, prayer), (_, expected) in zip(times.in_order(), at_65.in_order()):
        assert prayer.time == expected.time, name
        if name == "dhuhr":
            # Solar noon depends only on longitude, so nothing was replaced.
            assert prayer.high_latitude_rule is None
        else:
            assert prayer.high_latitude_rule == HighLatitudeRule.NEAREST_LATITUDE, name


def test_far_south_works_too():
    # McMurdo Station in Antarctica, at 77.8 degrees south, uses the times at 65 south.
    times = calculate(MCMURDO, WINTER_SOLSTICE)
    at_65_south = calculate_prayer_times(-65, MCMURDO.longitude, WINTER_SOLSTICE, MCMURDO.timezone)
    assert times.maghrib.time == at_65_south.maghrib.time
    assert times.maghrib.high_latitude_rule == HighLatitudeRule.NEAREST_LATITUDE
