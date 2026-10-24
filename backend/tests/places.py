"""Places and dates shared by the prayer time tests."""

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Place:
    name: str
    latitude: float
    longitude: float
    timezone: str


OTTAWA = Place("Ottawa", 45.4215, -75.6972, "America/Toronto")
TORONTO = Place("Toronto", 43.6532, -79.3832, "America/Toronto")
EDMONTON = Place("Edmonton", 53.5461, -113.4938, "America/Edmonton")
MECCA = Place("Mecca", 21.4225, 39.8262, "Asia/Riyadh")
LONDON = Place("London", 51.5074, -0.1278, "Europe/London")
SYDNEY = Place("Sydney", -33.8688, 151.2093, "Australia/Sydney")
KARACHI = Place("Karachi", 24.8607, 67.0011, "Asia/Karachi")

# Newfoundland is 3.5 hours behind UTC, a half hour offset.
ST_JOHNS = Place("St. John's", 47.5615, -52.7126, "America/St_Johns")
# Sun sets every day, but summer nights never get dark enough for Fajr and Isha.
IQALUIT = Place("Iqaluit", 63.7467, -68.5170, "America/Iqaluit")
# Midnight sun in summer, and no sunrise in December.
INUVIK = Place("Inuvik", 68.3607, -133.7230, "America/Inuvik")
ALERT = Place("Alert", 82.5018, -62.3481, "America/Iqaluit")
MCMURDO = Place("McMurdo Station", -77.8463, 166.6682, "Antarctica/McMurdo")

REFERENCE_CITIES = [OTTAWA, TORONTO, EDMONTON, MECCA, LONDON, SYDNEY, KARACHI]
ALL_PLACES = REFERENCE_CITIES + [ST_JOHNS, IQALUIT, INUVIK, ALERT, MCMURDO]

# 2028 is a leap year, so February 29 is covered too.
YEARS = [2026, 2028]


def days_in(year: int):
    """Every date in the year, one calendar day at a time."""
    day = date(year, 1, 1)
    while day.year == year:
        yield day
        day += timedelta(days=1)


def place_id(place: Place) -> str:
    """Readable test names in pytest output, like test_x[Ottawa]."""
    return place.name
