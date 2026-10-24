"""Compare our prayer times with two well-known libraries, every day of a year.

adhanpy is the Python version of adhan, the library behind many prayer apps.
praytimes is the Python version of PrayTimes.org.
Only the tests use them. The app never does.

There are two places where we differ from adhanpy on purpose:

1. Asr. Asr starts when a shadow is its noon length plus 1 (or 2) object lengths.
   adhanpy works out the noon shadow from where the sun is at midnight UTC, not
   at noon. At Edmonton that moves Asr by up to 2 minutes. We use where the sun
   is at noon. PrayTimes uses where the sun is at Asr, which lands within 40
   seconds of ours, so Asr is compared with PrayTimes.

2. Fajr when a high latitude rule is used. The rule takes a fraction of the
   night. We use the night that Fajr ends: last sunset to this sunrise. adhanpy
   uses the night after this day. So Fajr is checked against adhanpy's own
   sunrise and sunset times, with our rule applied to them.

Those two checks use times before rounding. The rest compare the rounded times
that users see.
"""

import math
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from adhanpy.astronomy.SolarTime import SolarTime
from adhanpy.calculation.CalculationMethod import CalculationMethod as AdhanMethod
from adhanpy.calculation.CalculationParameters import CalculationParameters
from adhanpy.calculation.HighLatitudeRule import HighLatitudeRule as AdhanHighLatitudeRule
from adhanpy.data.Coordinates import Coordinates
from adhanpy.PrayerTimes import PrayerTimes as AdhanPrayerTimes
from adhanpy.util.DateComponents import DateComponents
from praytimes import PrayTimes

from app.prayer_times import AsrMethod, CalculationMethod, calculate_prayer_times
from tests.places import REFERENCE_CITIES, YEARS, days_in, place_id

# praytimes is old and calls re.split in a way newer Python warns about. Not our code.
pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning:praytimes")

ONE_MINUTE = timedelta(minutes=1)

ADHAN_METHODS = {
    CalculationMethod.ISNA: AdhanMethod.NORTH_AMERICA,
    CalculationMethod.MWL: AdhanMethod.MUSLIM_WORLD_LEAGUE,
    CalculationMethod.EGYPTIAN: AdhanMethod.EGYPTIAN,
    CalculationMethod.KARACHI: AdhanMethod.KARACHI,
    CalculationMethod.UMM_AL_QURA: AdhanMethod.UMM_AL_QURA,
}


def _utc(day, hours):
    return datetime.combine(day, time(), tzinfo=timezone.utc) + timedelta(hours=hours)


def _adhanpy_fajr(place, day, fajr_angle):
    """Fajr from adhanpy's sun times, using our night for the high latitude rule."""
    coordinates = Coordinates(place.latitude, place.longitude)
    yesterday = day - timedelta(days=1)
    sun_today = SolarTime(DateComponents(day.year, day.month, day.day), coordinates)
    sun_yesterday = SolarTime(
        DateComponents(yesterday.year, yesterday.month, yesterday.day), coordinates
    )

    sunrise = _utc(day, sun_today.sunrise)
    last_sunset = _utc(yesterday, sun_yesterday.sunset)
    portion = 1 / 7 if abs(place.latitude) >= 48 else 1 / 2
    earliest = sunrise - portion * (sunrise - last_sunset)

    angle_hours = sun_today.hour_angle(-fajr_angle, False)
    if math.isnan(angle_hours):  # the sun never got that far down
        return earliest
    return max(_utc(day, angle_hours), earliest)


@pytest.mark.parametrize("year", YEARS)
@pytest.mark.parametrize("method", list(CalculationMethod))
@pytest.mark.parametrize("place", REFERENCE_CITIES, ids=place_id)
def test_matches_adhanpy(place, method, year):
    params = CalculationParameters(method=ADHAN_METHODS[method])
    # Match our high latitude rule. adhanpy's default is middle of the night everywhere.
    params.high_latitude_rule = (
        AdhanHighLatitudeRule.SEVENTH_OF_THE_NIGHT
        if abs(place.latitude) >= 48
        else AdhanHighLatitudeRule.MIDDLE_OF_THE_NIGHT
    )
    zone = ZoneInfo(place.timezone)

    mismatches = []
    for day in days_in(year):
        ours = calculate_prayer_times(
            place.latitude, place.longitude, day, place.timezone, method
        )
        theirs = AdhanPrayerTimes(
            (place.latitude, place.longitude),
            datetime(day.year, day.month, day.day),
            calculation_parameters=params,
            time_zone=zone,
        )

        for name in ("sunrise", "dhuhr", "maghrib", "isha"):
            our_time = getattr(ours, name).time
            their_time = getattr(theirs, name)
            if abs(our_time - their_time) > ONE_MINUTE:
                mismatches.append(f"{day} {name}: ours {our_time}, adhanpy {their_time}")

        expected_fajr = _adhanpy_fajr(place, day, params.fajr_angle)
        if abs(ours.fajr.exact_time - expected_fajr) > ONE_MINUTE:
            mismatches.append(f"{day} fajr: ours {ours.fajr.exact_time}, adhanpy {expected_fajr}")

    assert not mismatches, "\n".join(mismatches[:20])


@pytest.mark.parametrize("year", YEARS)
@pytest.mark.parametrize("asr_method", list(AsrMethod))
@pytest.mark.parametrize("place", REFERENCE_CITIES, ids=place_id)
def test_asr_matches_praytimes(place, asr_method, year):
    praytimes = PrayTimes()
    praytimes.adjust({"asr": "Hanafi" if asr_method == AsrMethod.HANAFI else "Standard"})

    mismatches = []
    for day in days_in(year):
        ours = calculate_prayer_times(
            place.latitude, place.longitude, day, place.timezone, asr_method=asr_method
        ).asr.exact_time
        # Time zone 0 asks for hours after midnight UTC.
        hours = praytimes.getTimes(day, (place.latitude, place.longitude), 0, format="Float")["asr"]
        theirs = _utc(day, hours)
        # PrayTimes keeps hours between 0 and 24, so an Asr after midnight UTC
        # (Edmonton in summer) comes back a day early. Move it to the nearest day.
        theirs += timedelta(days=round((ours - theirs) / timedelta(days=1)))
        if abs(ours - theirs) > ONE_MINUTE:
            mismatches.append(f"{day} asr: ours {ours}, praytimes {theirs}")

    assert not mismatches, "\n".join(mismatches[:20])
