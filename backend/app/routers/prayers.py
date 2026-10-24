"""Add today's prayers to the user's Prayers calendar in Google."""

import os
import uuid
from datetime import date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx2
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.auth.sessions import current_user
from app.auth.tokens import get_access_token
from app.clock import get_now
from app.db import get_db
from app.google_calendar import GoogleCalendar
from app.google_errors import GoogleError, GoogleTemporaryError
from app.http_client import get_http
from app.models import PrayerEvent, User
from app.prayer_sync import SyncIncomplete, events_for_day, save_day, send_to_google
from app.prayer_times import DEFAULT_TIMEZONE, AsrMethod, CalculationMethod, calculate_prayer_times
from app.prayers_calendar import CALENDAR_NAME, ensure_prayers_calendar

router = APIRouter(tags=["prayers"])


def _default_timezone() -> str:
    return os.environ.get("DEFAULT_TIMEZONE", DEFAULT_TIMEZONE)


def _check_timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    # ValueError covers names that aren't valid paths, like "../etc/passwd".
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"Unknown time zone: {name}")
    return name


class TodayRequest(BaseModel):
    """No saved settings yet (milestone 4), so the location comes with each request."""

    # The example fills in /docs, so "Try it out" works straight away.
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "latitude": 45.4215,
                    "longitude": -75.6972,
                    "timezone": "America/Toronto",
                    "method": "isna",
                    "asr_method": "standard",
                }
            ]
        }
    )

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str = Field(default_factory=_default_timezone, description="Like America/Toronto")
    method: CalculationMethod = CalculationMethod.ISNA
    asr_method: AsrMethod = AsrMethod.STANDARD

    @field_validator("timezone")
    @classmethod
    def timezone_must_exist(cls, name: str) -> str:
        return _check_timezone(name)


class PrayerEventResponse(BaseModel):
    prayer: str
    starts_at: datetime  # in the event's own time zone
    ends_at: datetime
    time_zone: str
    source: str
    sync_status: str
    app_event_id: uuid.UUID


class TodayResponse(BaseModel):
    date: date
    calendar: str
    events: list[PrayerEventResponse]


def _event_response(row: PrayerEvent) -> PrayerEventResponse:
    zone = ZoneInfo(row.time_zone)
    return PrayerEventResponse(
        prayer=row.prayer,
        starts_at=row.starts_at.astimezone(zone),
        ends_at=row.ends_at.astimezone(zone),
        time_zone=row.time_zone,
        source=row.source_description,
        sync_status=row.sync_status,
        app_event_id=row.id,
    )


def _google_failed(error: GoogleError, saved: list[str], waiting: list[str]) -> HTTPException:
    temporary = isinstance(error, GoogleTemporaryError)
    return HTTPException(
        # 503: try again later. 502: Google gave an answer we can't use.
        status_code=503 if temporary else 502,
        detail={
            "message": (
                "Google failed partway. Run it again to finish."
                if temporary
                else "Google refused a request. Nothing was duplicated."
            ),
            "error": str(error),
            "saved": saved,
            "waiting": waiting,
        },
    )


@router.post("/prayers/today", response_model=TodayResponse)
def add_today_prayers(
    request: TodayRequest,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    http: Annotated[httpx2.Client, Depends(get_http)],
    now: Annotated[datetime, Depends(get_now)],
) -> TodayResponse:
    """Add today's 5 prayers to the Prayers calendar. Safe to run again: it updates, never duplicates."""
    # "Today" in the place's time zone, not the server's.
    today = now.astimezone(ZoneInfo(request.timezone)).date()
    try:
        day = calculate_prayer_times(
            request.latitude, request.longitude, today, request.timezone, request.method, request.asr_method
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))

    # Saved before anything goes to Google.
    rows = save_day(db, user.id, day)

    calendar = GoogleCalendar(http, lambda force: get_access_token(db, http, user.id, force))
    # Get (or refresh) the token first, so a dead sign-in is reported before any Google call.
    get_access_token(db, http, user.id)
    try:
        prayers_calendar = ensure_prayers_calendar(db, calendar, user.id, request.timezone)
        send_to_google(db, calendar, prayers_calendar.google_calendar_id, rows)
    except SyncIncomplete as incomplete:
        raise _google_failed(incomplete.error, incomplete.saved, incomplete.waiting)
    except GoogleError as error:
        raise _google_failed(error, [], [row.prayer for row in rows])

    return TodayResponse(
        date=today, calendar=CALENDAR_NAME, events=[_event_response(row) for row in rows]
    )


@router.get("/prayers/today/events", response_model=list[PrayerEventResponse])
def list_today_events(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    now: Annotated[datetime, Depends(get_now)],
    timezone: Annotated[str | None, Query(description="Like America/Toronto")] = None,
) -> list[PrayerEventResponse]:
    """Your saved events for today, from the database. Only ever your own."""
    timezone = timezone or _default_timezone()
    try:
        today = now.astimezone(ZoneInfo(_check_timezone(timezone))).date()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return [_event_response(row) for row in events_for_day(db, user.id, today)]
