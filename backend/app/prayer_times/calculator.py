"""Daily prayer times for one place and one local date.

This only does maths. It has no database and no web code, so it's easy to test.
"""

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from zoneinfo import ZoneInfo

from app.prayer_times.astronomy import SUNRISE_ALTITUDE, SolarDay
from app.prayer_times.methods import (
    METHODS,
    SHADOW_LENGTHS,
    AsrMethod,
    CalculationMethod,
    MethodSettings,
)

DEFAULT_TIMEZONE = "America/Toronto"

PRAYER_NAMES = ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")

# Below 48 degrees the night is long enough that the middle of the night is a
# fine limit. Above it, summer nights are short, so the limit is tighter.
# The same cut-off as the adhan library's recommended rule.
SEVENTH_OF_THE_NIGHT_FROM = 48

# Above about 65.7 degrees there are days with no sunset (midnight sun) or no
# sunrise (polar night). 65 degrees still has both every day of the year.
NEAREST_LATITUDE = 65


class HighLatitudeRule(StrEnum):
    """Which fallback replaced a time that the normal method couldn't give."""

    # Fajr is never earlier than the middle of the night, and Isha never later.
    MIDDLE_OF_THE_NIGHT = "middle_of_the_night"
    # Fajr is never earlier than the last seventh of the night, and Isha never
    # later than the first seventh.
    SEVENTH_OF_THE_NIGHT = "seventh_of_the_night"
    # The sun doesn't rise or set at all, so use the times at 65 degrees
    # latitude, the nearest place where it does.
    NEAREST_LATITUDE = "nearest_latitude"


@dataclass(frozen=True)
class PrayerTime:
    time: datetime  # rounded to the minute, in the local time zone
    exact_time: datetime  # before rounding, in UTC
    method: CalculationMethod
    asr_method: AsrMethod
    high_latitude_rule: HighLatitudeRule | None = None
    # Every time from this module is calculated. Later, masjid times will say
    # "published by the masjid" here instead, so users can tell them apart.
    source: str = "calculated"


@dataclass(frozen=True)
class DailyPrayerTimes:
    date: date
    timezone: str
    latitude: float
    longitude: float
    method: CalculationMethod
    asr_method: AsrMethod
    fajr: PrayerTime
    sunrise: PrayerTime
    dhuhr: PrayerTime
    asr: PrayerTime
    maghrib: PrayerTime
    isha: PrayerTime

    def in_order(self) -> list[tuple[str, PrayerTime]]:
        return [(name, getattr(self, name)) for name in PRAYER_NAMES]


def round_up_to_minute(moment: datetime) -> datetime:
    """12:00:00 stays 12:00. 12:00:01 becomes 12:01.

    Used for prayer start times, so the app never shows a prayer before it starts.
    """
    floored = moment.replace(second=0, microsecond=0)
    return floored if floored == moment else floored + timedelta(minutes=1)


def round_down_to_minute(moment: datetime) -> datetime:
    """5:59:59 becomes 5:59.

    Used for sunrise, since sunrise is when Fajr ends. Showing it early is safe.
    """
    return moment.replace(second=0, microsecond=0)


def _utc_datetime(day: date, hours: float) -> datetime:
    # Adding hours is only safe because this is UTC, which has no daylight saving.
    return datetime.combine(day, time(), tzinfo=timezone.utc) + timedelta(hours=hours)


def _utc_day_for(local_date: date, latitude: float, longitude: float, zone: ZoneInfo) -> date:
    """Find the UTC date whose solar noon falls on local_date in this time zone.

    Usually it's the same date. Near the date line it can be the day before or
    after, for example in Samoa, where it's already tomorrow compared to UTC.
    """
    for days in (0, -1, 1):
        # A date plus days=1 is the next calendar date, not 24 hours later.
        utc_day = local_date + timedelta(days=days)
        noon = _utc_datetime(utc_day, SolarDay(utc_day, latitude, longitude).noon())
        if noon.astimezone(zone).date() == local_date:
            return utc_day
    raise ValueError(f"Couldn't find solar noon on {local_date} in {zone.key}.")


def _night_limit_rule(latitude: float) -> tuple[HighLatitudeRule, float]:
    if abs(latitude) >= SEVENTH_OF_THE_NIGHT_FROM:
        return HighLatitudeRule.SEVENTH_OF_THE_NIGHT, 1 / 7
    return HighLatitudeRule.MIDDLE_OF_THE_NIGHT, 1 / 2


def _exact_times(
    utc_day: date,
    latitude: float,
    longitude: float,
    settings: MethodSettings,
    shadow_length: int,
) -> dict[str, tuple[datetime, HighLatitudeRule | None]] | None:
    """Unrounded UTC times, each with the high latitude rule used (if any).

    Returns None if the sun doesn't rise or set on this day or the nights
    around it, because then there's no night to measure.
    """
    yesterday = SolarDay(utc_day - timedelta(days=1), latitude, longitude)
    today = SolarDay(utc_day, latitude, longitude)
    tomorrow = SolarDay(utc_day + timedelta(days=1), latitude, longitude)

    hours = {
        "last_sunset": yesterday.time_at_altitude(SUNRISE_ALTITUDE, after_noon=True),
        "sunrise": today.time_at_altitude(SUNRISE_ALTITUDE, after_noon=False),
        "sunset": today.time_at_altitude(SUNRISE_ALTITUDE, after_noon=True),
        "next_sunrise": tomorrow.time_at_altitude(SUNRISE_ALTITUDE, after_noon=False),
    }
    if None in hours.values():
        return None

    last_sunset = _utc_datetime(utc_day - timedelta(days=1), hours["last_sunset"])
    sunrise = _utc_datetime(utc_day, hours["sunrise"])
    sunset = _utc_datetime(utc_day, hours["sunset"])
    next_sunrise = _utc_datetime(utc_day + timedelta(days=1), hours["next_sunrise"])

    noon_hours = today.noon()
    dhuhr = _utc_datetime(utc_day, noon_hours) + timedelta(
        minutes=settings.dhuhr_minutes_after_noon
    )

    # Asr: a shadow equal to the noon shadow plus shadow_length times the
    # object's height. The noon shadow uses the sun's declination at noon.
    noon_declination = today.declination_at(noon_hours)
    noon_shadow = math.tan(math.radians(abs(latitude - noon_declination)))
    asr_altitude = math.degrees(math.atan(1 / (shadow_length + noon_shadow)))
    asr_hours = today.time_at_altitude(asr_altitude, after_noon=True)
    if asr_hours is None:
        return None
    asr = _utc_datetime(utc_day, asr_hours)

    rule, portion = _night_limit_rule(latitude)

    # Fajr is at the end of the night before this day, so it uses that night.
    earliest_fajr = sunrise - portion * (sunrise - last_sunset)
    fajr_hours = today.time_at_altitude(-settings.fajr_angle, after_noon=False)
    fajr = None if fajr_hours is None else _utc_datetime(utc_day, fajr_hours)
    fajr_rule = None
    if fajr is None or fajr < earliest_fajr:
        fajr, fajr_rule = earliest_fajr, rule

    isha_rule = None
    if settings.isha_minutes_after_maghrib is not None:
        isha = sunset + timedelta(minutes=settings.isha_minutes_after_maghrib)
    else:
        latest_isha = sunset + portion * (next_sunrise - sunset)
        isha_hours = today.time_at_altitude(-settings.isha_angle, after_noon=True)
        isha = None if isha_hours is None else _utc_datetime(utc_day, isha_hours)
        if isha is None or isha > latest_isha:
            isha, isha_rule = latest_isha, rule

    return {
        "fajr": (fajr, fajr_rule),
        "sunrise": (sunrise, None),
        "dhuhr": (dhuhr, None),
        "asr": (asr, None),
        "maghrib": (sunset, None),
        "isha": (isha, isha_rule),
    }


def calculate_prayer_times(
    latitude: float,
    longitude: float,
    on_date: date,
    time_zone: str = DEFAULT_TIMEZONE,
    method: CalculationMethod = CalculationMethod.ISNA,
    asr_method: AsrMethod = AsrMethod.STANDARD,
) -> DailyPrayerTimes:
    """Calculate Fajr, Sunrise, Dhuhr, Asr, Maghrib, and Isha.

    on_date is a local date in time_zone, like a date on a wall calendar.
    time_zone is an IANA name like "America/Toronto". A name that doesn't
    exist raises zoneinfo.ZoneInfoNotFoundError.
    """
    if not -90 <= latitude <= 90:
        raise ValueError(f"Latitude must be between -90 and 90, got {latitude}.")
    if not -180 <= longitude <= 180:
        raise ValueError(f"Longitude must be between -180 and 180, got {longitude}.")

    zone = ZoneInfo(time_zone)
    settings = METHODS[method]
    shadow_length = SHADOW_LENGTHS[asr_method]
    utc_day = _utc_day_for(on_date, latitude, longitude, zone)

    times = _exact_times(utc_day, latitude, longitude, settings, shadow_length)
    if times is None:
        nearest = math.copysign(NEAREST_LATITUDE, latitude)
        times = _exact_times(utc_day, nearest, longitude, settings, shadow_length)
        if times is None:
            raise ValueError(f"Couldn't calculate prayer times at latitude {latitude}.")
        # Dhuhr only depends on longitude, so it didn't change.
        times = {
            name: (moment, None if name == "dhuhr" else HighLatitudeRule.NEAREST_LATITUDE)
            for name, (moment, _) in times.items()
        }

    def build(name: str) -> PrayerTime:
        exact, rule = times[name]
        rounded = round_down_to_minute(exact) if name == "sunrise" else round_up_to_minute(exact)
        return PrayerTime(
            time=rounded.astimezone(zone),
            exact_time=exact,
            method=method,
            asr_method=asr_method,
            high_latitude_rule=rule,
        )

    return DailyPrayerTimes(
        date=on_date,
        timezone=time_zone,
        latitude=latitude,
        longitude=longitude,
        method=method,
        asr_method=asr_method,
        **{name: build(name) for name in PRAYER_NAMES},
    )
