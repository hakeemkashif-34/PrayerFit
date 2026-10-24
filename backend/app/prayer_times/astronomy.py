"""Where the sun is in the sky on a given day, and when it reaches an altitude.

The formulas come from Jean Meeus, "Astronomical Algorithms" (2nd edition).
Each function names the chapter it comes from, so it can be checked against the book.
The adhan prayer times library is built on the same book, so the tests can compare
against it.

Everything here works in UTC. Times are returned as hours after midnight UTC
on the given date, as plain floats. They can be negative or above 24, which
means the previous or next UTC day. calculator.py turns them into real datetimes.

Angles are in degrees. Longitude is positive east, like on a map.
"""

import math
from dataclasses import dataclass
from datetime import date

# The sun's centre is 50 arcminutes below the horizon at sunrise and sunset:
# 34 for air bending the light (refraction), plus 16 for half the sun's width.
SUNRISE_ALTITUDE = -50 / 60

# time_at_altitude stops searching when it has the time to within this many
# days (about 0.01 seconds).
CLOSE_ENOUGH = 1e-7


def _sin(degrees: float) -> float:
    return math.sin(math.radians(degrees))


def _cos(degrees: float) -> float:
    return math.cos(math.radians(degrees))


def _normalize(angle: float) -> float:
    """Put an angle in the range [0, 360)."""
    return angle % 360


def _wrap_180(angle: float) -> float:
    """Put an angle in the range (-180, 180]."""
    angle = angle % 360
    return angle - 360 if angle > 180 else angle


def julian_day(day: date) -> float:
    """Days since 4713 BC at midnight UTC on this date. Chapter 7.

    Astronomers count days this way so the gap between two dates is
    a simple subtraction, with no months or leap years to handle.
    """
    year, month = day.year, day.month
    if month <= 2:
        year -= 1
        month += 12
    century = year // 100
    gregorian_fix = 2 - century + century // 4
    return (
        math.floor(365.25 * (year + 4716))
        + math.floor(30.6001 * (month + 1))
        + day.day
        + gregorian_fix
        - 1524.5
    )


@dataclass(frozen=True)
class SunPosition:
    """The sun's place in the sky at midnight UTC on one date."""

    declination: float  # how far north (+) or south (-) of the equator the sun is
    right_ascension: float  # the sun's "longitude" on the sky, 0 to 360
    sidereal_time: float  # how far the Earth has turned at Greenwich, 0 to 360


def sun_position(jd: float) -> SunPosition:
    """Chapters 12, 22, and 25 (the low accuracy version, good to about 0.01 degrees)."""
    t = (jd - 2451545.0) / 36525  # centuries since 1 January 2000 at noon

    # Chapter 25: the sun's position along its yearly path.
    mean_longitude = _normalize(280.46646 + 36000.76983 * t + 0.0003032 * t**2)
    mean_anomaly = 357.52911 + 35999.05029 * t - 0.0001537 * t**2
    # The Earth's orbit is an ellipse, not a circle, so the sun speeds up and slows down.
    equation_of_centre = (
        (1.914602 - 0.004817 * t - 0.000014 * t**2) * _sin(mean_anomaly)
        + (0.019993 - 0.000101 * t) * _sin(2 * mean_anomaly)
        + 0.000289 * _sin(3 * mean_anomaly)
    )
    moon_node = 125.04 - 1934.136 * t
    # Corrected for aberration and the Earth's wobble (nutation).
    apparent_longitude = mean_longitude + equation_of_centre - 0.00569 - 0.00478 * _sin(moon_node)

    # Chapter 22: the tilt of the Earth's axis, and the wobble in it.
    mean_obliquity = 23.4392911 - 0.0130041667 * t - 1.639e-7 * t**2 + 5.036e-7 * t**3
    moon_mean_longitude = 218.3165 + 481267.8813 * t
    nutation_longitude = (
        -17.20 * _sin(moon_node)
        - 1.32 * _sin(2 * mean_longitude)
        - 0.23 * _sin(2 * moon_mean_longitude)
        + 0.21 * _sin(2 * moon_node)
    ) / 3600
    nutation_obliquity = (
        9.20 * _cos(moon_node)
        + 0.57 * _cos(2 * mean_longitude)
        + 0.10 * _cos(2 * moon_mean_longitude)
        - 0.09 * _cos(2 * moon_node)
    ) / 3600

    # Chapter 25: turn the position along the path into sky coordinates.
    obliquity = mean_obliquity + 0.00256 * _cos(moon_node)
    declination = math.degrees(math.asin(_sin(obliquity) * _sin(apparent_longitude)))
    right_ascension = _normalize(
        math.degrees(
            math.atan2(_cos(obliquity) * _sin(apparent_longitude), _cos(apparent_longitude))
        )
    )

    # Chapter 12: how far the Earth has turned, measured against the stars.
    mean_sidereal = _normalize(
        280.46061837
        + 360.98564736629 * (jd - 2451545.0)
        + 0.000387933 * t**2
        - t**3 / 38710000
    )
    sidereal_time = mean_sidereal + nutation_longitude * _cos(mean_obliquity + nutation_obliquity)

    return SunPosition(declination, right_ascension, sidereal_time)


def _interpolate(before: float, today: float, after: float, n: float) -> float:
    """Estimate a value n days after today from three daily values. Chapter 3."""
    a = today - before
    b = after - today
    return today + n / 2 * (a + b + n * (b - a))


def _interpolate_angle(before: float, today: float, after: float, n: float) -> float:
    """Same as _interpolate, but handles an angle jumping from 359 back to 0."""
    a = _wrap_180(today - before)
    b = _wrap_180(after - today)
    return today + n / 2 * (a + b + n * (b - a))


def altitude(latitude: float, declination: float, hour_angle: float) -> float:
    """How high the sun is above the horizon, in degrees. Chapter 13."""
    return math.degrees(
        math.asin(
            _sin(latitude) * _sin(declination)
            + _cos(latitude) * _cos(declination) * _cos(hour_angle)
        )
    )


class SolarDay:
    """The sun's path over one place on one UTC date. Chapter 15.

    Solar noon uses the book's method: guess from the sun's position, then
    correct once. For the other times we search with binary search, explained
    in time_at_altitude.
    """

    def __init__(self, day: date, latitude: float, longitude: float):
        self.latitude = latitude
        self.longitude = longitude
        jd = julian_day(day)
        # Positions for yesterday, today, and tomorrow, so we can estimate
        # where the sun is at any moment in between.
        self._before = sun_position(jd - 1)
        self._today = sun_position(jd)
        self._after = sun_position(jd + 1)
        # First guess at solar noon, as a fraction of the day (0 to 1).
        self._noon_guess = (
            (self._today.right_ascension - longitude - self._today.sidereal_time) / 360
        ) % 1

    def _hour_angle_at(self, m: float) -> tuple[float, float]:
        """The sun's hour angle and declination at m days after midnight UTC.

        The hour angle is how far (in degrees) the sun is past this place's
        meridian: 0 at solar noon, negative in the morning, positive after.
        """
        sidereal = self._today.sidereal_time + 360.985647 * m
        right_ascension = _interpolate_angle(
            self._before.right_ascension,
            self._today.right_ascension,
            self._after.right_ascension,
            m,
        )
        declination = _interpolate(
            self._before.declination, self._today.declination, self._after.declination, m
        )
        return _wrap_180(sidereal + self.longitude - right_ascension), declination

    def _altitude_at(self, m: float) -> float:
        hour_angle, declination = self._hour_angle_at(m)
        return altitude(self.latitude, declination, hour_angle)

    def noon(self) -> float:
        """Solar noon (transit): the moment the sun is highest. Hours after midnight UTC."""
        hour_angle, _ = self._hour_angle_at(self._noon_guess)
        return (self._noon_guess - hour_angle / 360) * 24

    def declination_at(self, hours: float) -> float:
        """The sun's declination at this many hours after midnight UTC."""
        _, declination = self._hour_angle_at(hours / 24)
        return declination

    def time_at_altitude(self, target: float, after_noon: bool) -> float | None:
        """When the sun is at this altitude, in hours after midnight UTC.

        Negative altitudes are below the horizon (Fajr and Isha use -15 to -19.5).
        Returns None if the sun never reaches that altitude on this day,
        which happens far north in summer, when it never gets dark enough.

        Binary search: from solar noon to solar midnight the sun only goes down,
        so the time is somewhere in that half day. Check the middle, keep the
        half that still has the answer, and repeat. Each step halves the gap,
        so about 23 steps get from half a day to 0.01 seconds.

        The book's method (guess, then correct) is faster, but on days when the
        sun only just reaches the target, a correction can be minutes off or even
        land on the wrong day. Binary search can't do that.
        """
        noon = self.noon() / 24
        midnight = noon + (0.5 if after_noon else -0.5)
        # Midnight is the sun's lowest point, so if it's still above the target
        # there (or still below it at noon), the sun never crosses it today.
        if self._altitude_at(noon) < target or self._altitude_at(midnight) > target:
            return None

        high, low = noon, midnight  # the sun is above the target at high, below at low
        while abs(high - low) > CLOSE_ENOUGH:
            middle = (high + low) / 2
            if self._altitude_at(middle) > target:
                high = middle
            else:
                low = middle
        return (high + low) / 2 * 24
