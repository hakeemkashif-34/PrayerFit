"""GET /prayer-times: calculated prayer times for one place and one day."""

import os
from datetime import date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.prayer_times import (
    DEFAULT_TIMEZONE,
    AsrMethod,
    CalculationMethod,
    HighLatitudeRule,
    calculate_prayer_times,
)

router = APIRouter()


class PrayerTimeResponse(BaseModel):
    time: datetime
    source: str
    method: CalculationMethod
    asr_method: AsrMethod
    # Set only when a high latitude rule replaced the normal time.
    high_latitude_rule: HighLatitudeRule | None


class PrayerTimesResponse(BaseModel):
    date: date
    timezone: str
    latitude: float
    longitude: float
    method: CalculationMethod
    asr_method: AsrMethod
    # Keys in order: fajr, sunrise, dhuhr, asr, maghrib, isha.
    times: dict[str, PrayerTimeResponse]


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    # ValueError covers names that aren't valid paths, like "../etc/passwd".
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(status_code=422, detail=f"Unknown time zone: {name}")


@router.get("/prayer-times", response_model=PrayerTimesResponse)
def get_prayer_times(
    latitude: Annotated[float, Query(ge=-90, le=90)],
    longitude: Annotated[float, Query(ge=-180, le=180)],
    # Called on_date in Python so it doesn't hide the date type. It's still ?date= in the URL.
    on_date: Annotated[date | None, Query(alias="date", description="Defaults to today")] = None,
    method: CalculationMethod = CalculationMethod.ISNA,
    asr_method: AsrMethod = AsrMethod.STANDARD,
    timezone: Annotated[str | None, Query(description="Like America/Toronto")] = None,
):
    """Return Fajr, Sunrise, Dhuhr, Asr, Maghrib, and Isha, and where each came from."""
    timezone = timezone or os.environ.get("DEFAULT_TIMEZONE", DEFAULT_TIMEZONE)
    zone = _zone(timezone)
    if on_date is None:
        # "Today" in the place's time zone, not the server's.
        on_date = datetime.now(zone).date()

    try:
        result = calculate_prayer_times(latitude, longitude, on_date, timezone, method, asr_method)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))

    return PrayerTimesResponse(
        date=result.date,
        timezone=result.timezone,
        latitude=result.latitude,
        longitude=result.longitude,
        method=result.method,
        asr_method=result.asr_method,
        times={
            name: PrayerTimeResponse(
                time=prayer.time,
                source=prayer.source,
                method=prayer.method,
                asr_method=prayer.asr_method,
                high_latitude_rule=prayer.high_latitude_rule,
            )
            for name, prayer in result.in_order()
        },
    )
