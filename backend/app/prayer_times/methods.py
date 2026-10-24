"""Calculation methods and Asr methods.

Groups of scholars disagree on how dark the sky has to be for Fajr to start
and Isha to start. Each "calculation method" is one group's answer, given as
how many degrees the sun is below the horizon.
"""

from dataclasses import dataclass
from enum import StrEnum


class CalculationMethod(StrEnum):
    ISNA = "isna"  # Islamic Society of North America. The default, since most masjids here use it.
    MWL = "mwl"  # Muslim World League
    EGYPTIAN = "egyptian"  # Egyptian General Authority of Survey
    KARACHI = "karachi"  # University of Islamic Sciences, Karachi
    UMM_AL_QURA = "umm_al_qura"  # Umm al-Qura University, Makkah


class AsrMethod(StrEnum):
    """Asr starts when a stick's shadow is its noon shadow plus this many stick lengths."""

    STANDARD = "standard"  # 1 length: Shafi'i, Maliki, and Hanbali
    HANAFI = "hanafi"  # 2 lengths, so Hanafi Asr is always later


SHADOW_LENGTHS = {AsrMethod.STANDARD: 1, AsrMethod.HANAFI: 2}


@dataclass(frozen=True)
class MethodSettings:
    fajr_angle: float  # degrees below the horizon
    isha_angle: float | None  # degrees below the horizon, or None if Isha is a fixed gap
    isha_minutes_after_maghrib: int | None = None
    # Extra minutes after solar noon before Dhuhr starts. The sun's disc is
    # about 2 minutes wide, so its back edge crosses the meridian about 1
    # minute after its centre. These values match the adhan library.
    dhuhr_minutes_after_noon: int = 0


METHODS = {
    CalculationMethod.ISNA: MethodSettings(fajr_angle=15, isha_angle=15, dhuhr_minutes_after_noon=1),
    CalculationMethod.MWL: MethodSettings(fajr_angle=18, isha_angle=17, dhuhr_minutes_after_noon=1),
    CalculationMethod.EGYPTIAN: MethodSettings(
        fajr_angle=19.5, isha_angle=17.5, dhuhr_minutes_after_noon=1
    ),
    CalculationMethod.KARACHI: MethodSettings(
        fajr_angle=18, isha_angle=18, dhuhr_minutes_after_noon=1
    ),
    # Umm al-Qura sets Isha 90 minutes after Maghrib instead of using an angle.
    # In Ramadan it uses 120 minutes. That isn't handled yet.
    CalculationMethod.UMM_AL_QURA: MethodSettings(
        fajr_angle=18.5, isha_angle=None, isha_minutes_after_maghrib=90
    ),
}
