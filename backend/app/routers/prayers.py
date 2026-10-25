"""Add today's prayers to the user's Prayers calendar in Google."""

import os
import uuid
from datetime import date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

import httpx2
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.sessions import current_user
from app.calendar_window import SetupIncomplete, refresh_calendar, rows_for_dates
from app.clock import get_now
from app.db import get_db
from app.google_errors import GoogleError, GoogleTemporaryError
from app.http_client import get_http
from app.models import PrayerEvent, User
from app.prayer_sync import SyncIncomplete
from app.prayer_times import DEFAULT_TIMEZONE
from app.prayers_calendar import CALENDAR_NAME
from app.user_settings import get_settings

router = APIRouter(tags=["prayers"])


class PrayerEventResponse(BaseModel):
    prayer: str
    # "prayer", or "drive" for the drive block before a masjid prayer.
    kind: str
    title: str  # like "Dhuhr at KMA" or "Drive to KMA"
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
        kind=row.kind,
        title=row.summary or row.prayer.capitalize(),
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


def _user_today(db: Session, user_id: uuid.UUID, now: datetime) -> date:
    zone = get_settings(db, user_id).time_zone or os.environ.get("DEFAULT_TIMEZONE") or DEFAULT_TIMEZONE
    return now.astimezone(ZoneInfo(zone)).date()


@router.post("/prayers/today", response_model=TodayResponse)
def add_today_prayers(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    http: Annotated[httpx2.Client, Depends(get_http)],
    now: Annotated[datetime, Depends(get_now)],
) -> TodayResponse:
    """Add today's 5 prayers to the Prayers calendar, using your saved settings.

    Safe to run again: it updates, never duplicates.
    """
    try:
        result = refresh_calendar(db, http, user.id, now, days=1)
    except SetupIncomplete:
        raise HTTPException(status_code=409, detail={"message": "Finish setup first."})
    except SyncIncomplete as incomplete:
        raise _google_failed(incomplete.error, incomplete.saved, incomplete.waiting)
    except GoogleError as error:
        today = rows_for_dates(db, user.id, [_user_today(db, user.id, now)])
        raise _google_failed(error, [], [row.prayer for row in today if row.sync_status == "pending"])

    return TodayResponse(
        date=result.rows[0].local_date,
        calendar=CALENDAR_NAME,
        events=[_event_response(row) for row in result.rows],
    )


@router.get("/prayers/today/events", response_model=list[PrayerEventResponse])
def list_today_events(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    now: Annotated[datetime, Depends(get_now)],
) -> list[PrayerEventResponse]:
    """Your saved events for today, from the database. Only ever your own."""
    today = _user_today(db, user.id, now)
    rows = rows_for_dates(db, user.id, [today])
    return [_event_response(row) for row in rows if row.sync_status != "deleted"]
