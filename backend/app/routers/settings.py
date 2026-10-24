"""The setup questions and the settings page.

Setup and the Edit buttons use the same endpoints. During setup nothing
goes to Google. Once setup is finished, every change updates the
calendar straight away, but only the future events that changed.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

import httpx2
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth.sessions import current_user
from app.calendar_window import SetupIncomplete, refresh_calendar
from app.clock import get_now
from app.db import get_db
from app.geo.nominatim import find_address
from app.geo.overpass import SEARCH_RADIUS_KM, nearby_masjids
from app.geo.timezones import timezone_for
from app.google_errors import CalendarAccessMissing, GoogleError, ReauthRequired
from app.http_client import get_http
from app.models import Masjid, PrayerEvent, User, UserJumuahMasjid, WeeklyMasjidPrayers
from app.prayer_sync import SyncIncomplete
from app.prayer_times import AsrMethod, CalculationMethod
from app.user_settings import (
    PRAYERS,
    find_settings,
    get_settings,
    jumuah_masjids,
    missing_steps,
    read_address,
    read_location,
    read_place_name,
    save_location,
    usable_masjid,
    weekly_rows,
)

router = APIRouter(tags=["settings"])

OSM_CREDIT = "© OpenStreetMap contributors"
OSM_CREDIT_URL = "https://www.openstreetmap.org/copyright"
# Iqamah times come in milestone 5.
IQAMAH_STATUS = "Iqamah times not added yet"

UserDep = Annotated[User, Depends(current_user)]
DbDep = Annotated[Session, Depends(get_db)]
HttpDep = Annotated[httpx2.Client, Depends(get_http)]
NowDep = Annotated[datetime, Depends(get_now)]


# ---- What the website gets back ----


class MasjidOut(BaseModel):
    id: uuid.UUID
    name: str | None
    address: str | None
    # "openstreetmap" or "user" (typed in by this user)
    source: str
    distance_km: float | None = None
    iqamah_status: str = IQAMAH_STATUS


class WeekdayPrayers(BaseModel):
    """True means that prayer is usually at the masjid on this day."""

    weekday: int = Field(ge=0, le=6, description="0 is Monday, 6 is Sunday")
    fajr: bool = False
    dhuhr: bool = False
    asr: bool = False
    maghrib: bool = False
    isha: bool = False


class SettingsOut(BaseModel):
    setup_complete: bool
    # Setup steps not answered yet, in order.
    missing: list[str]
    address: str | None
    place_name: str | None
    time_zone: str | None
    method: CalculationMethod | None
    asr_method: AsrMethod | None
    main_masjid_choice: Literal["masjid", "home"] | None
    main_masjid: MasjidOut | None
    main_masjid_short_name: str | None
    weekly: list[WeekdayPrayers]
    jumuah_saved: bool
    jumuah_masjids: list[MasjidOut]


class CalendarUpdate(BaseModel):
    status: Literal["updated", "waiting", "sign_in_needed", "not_set_up"]
    sent: int = 0
    waiting: int = 0
    message: str


class SaveResponse(BaseModel):
    settings: SettingsOut
    # Empty during setup, when nothing goes to Google yet.
    calendar: CalendarUpdate | None = None


def _masjid_out(masjid: Masjid, distance: float | None = None) -> MasjidOut:
    return MasjidOut(
        id=masjid.id,
        name=masjid.name,
        address=masjid.address,
        source=masjid.source,
        distance_km=None if distance is None else round(distance, 1),
    )


def settings_out(db: Session, user_id: uuid.UUID) -> SettingsOut:
    row = find_settings(db, user_id)
    main = db.get(Masjid, row.main_masjid_id) if row.main_masjid_id else None
    missing = missing_steps(db, row)
    return SettingsOut(
        setup_complete=row.setup_completed_at is not None and not missing,
        missing=missing,
        address=read_address(row),
        place_name=read_place_name(row),
        time_zone=row.time_zone,
        method=row.method,
        asr_method=row.asr_method,
        main_masjid_choice=row.main_masjid_choice,
        main_masjid=_masjid_out(main) if main and row.main_masjid_choice == "masjid" else None,
        main_masjid_short_name=row.main_masjid_short_name,
        weekly=[
            WeekdayPrayers(weekday=d.weekday, **{p: getattr(d, p) for p in PRAYERS})
            for d in weekly_rows(db, user_id)
        ],
        jumuah_saved=row.jumuah_saved,
        jumuah_masjids=[_masjid_out(m) for m in jumuah_masjids(db, user_id)],
    )


def _pending_count(db: Session, user_id: uuid.UUID) -> int:
    return len(
        db.scalars(
            select(PrayerEvent.id).where(
                PrayerEvent.user_id == user_id, PrayerEvent.sync_status == "pending"
            )
        ).all()
    )


def update_calendar(db: Session, http: httpx2.Client, user_id: uuid.UUID, now: datetime) -> CalendarUpdate:
    """Refresh the calendar and say how it went. Settings are already saved by now."""
    try:
        result = refresh_calendar(db, http, user_id, now)
    except SetupIncomplete:
        return CalendarUpdate(
            status="not_set_up", message="Saved. Answer the question below so your calendar can update."
        )
    except (ReauthRequired, CalendarAccessMissing):
        return CalendarUpdate(
            status="sign_in_needed",
            waiting=_pending_count(db, user_id),
            message="Saved. Sign in again so your calendar can update.",
        )
    except SyncIncomplete as incomplete:
        return CalendarUpdate(
            status="waiting",
            sent=len(incomplete.saved),
            waiting=len(incomplete.waiting),
            message="Saved. Some prayers haven't reached Google Calendar yet. Try again in a minute.",
        )
    except GoogleError:
        return CalendarUpdate(
            status="waiting",
            waiting=_pending_count(db, user_id),
            message="Saved. Google Calendar didn't answer. Try again in a minute.",
        )
    changed = "1 event" if result.sent == 1 else f"{result.sent} events"
    return CalendarUpdate(status="updated", sent=result.sent, message=f"Calendar updated. {changed} sent to Google.")


def _saved(db: Session, http: httpx2.Client, user: User, now: datetime) -> SaveResponse:
    """Commit, then update the calendar if setup is already finished."""
    db.commit()
    row = get_settings(db, user.id)
    calendar = update_calendar(db, http, user.id, now) if row.setup_completed_at else None
    return SaveResponse(settings=settings_out(db, user.id), calendar=calendar)


# ---- Reading ----


@router.get("/settings", response_model=SettingsOut)
def read_settings(user: UserDep, db: DbDep) -> SettingsOut:
    """Your saved setup answers. Only ever your own."""
    return settings_out(db, user.id)


# ---- Step 1: address ----


class AddressRequest(BaseModel):
    # In the body, never the URL, so it can't end up in access logs.
    address: str = Field(min_length=3, max_length=300)

    @field_validator("address")
    @classmethod
    def strip(cls, value: str) -> str:
        return " ".join(value.split())


class FoundAddress(BaseModel):
    place_name: str
    latitude: float
    longitude: float
    time_zone: str
    credit: str = OSM_CREDIT
    credit_url: str = OSM_CREDIT_URL


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"message": "No place found for that address. Try adding the city or postal code."},
    )


@router.post("/setup/address/search", response_model=FoundAddress)
def search_address(request: AddressRequest, user: UserDep, db: DbDep, http: HttpDep, now: NowDep) -> FoundAddress:
    """Look the address up so the user can check it. Saves nothing."""
    found = find_address(db, http, request.address, now)
    if found is None:
        raise _not_found()
    return FoundAddress(
        place_name=found.place_name,
        latitude=found.latitude,
        longitude=found.longitude,
        time_zone=timezone_for(found.latitude, found.longitude),
    )


@router.put("/settings/address", response_model=SaveResponse)
def save_address(request: AddressRequest, user: UserDep, db: DbDep, http: HttpDep, now: NowDep) -> SaveResponse:
    """Save the address the user confirmed.

    The location comes from the same lookup the user just saw (it's cached),
    not from the browser, so it always matches what they confirmed.
    """
    found = find_address(db, http, request.address, now)
    if found is None:
        raise _not_found()
    save_location(
        get_settings(db, user.id), request.address, found, timezone_for(found.latitude, found.longitude)
    )
    return _saved(db, http, user, now)


# ---- Step 2: calculation method and Asr method ----


class MethodsRequest(BaseModel):
    method: CalculationMethod = CalculationMethod.ISNA
    asr_method: AsrMethod = AsrMethod.STANDARD


@router.put("/settings/methods", response_model=SaveResponse)
def save_methods(request: MethodsRequest, user: UserDep, db: DbDep, http: HttpDep, now: NowDep) -> SaveResponse:
    row = get_settings(db, user.id)
    row.method = request.method.value
    row.asr_method = request.asr_method.value
    return _saved(db, http, user, now)


# ---- Step 3: main masjid ----


class NearbyResponse(BaseModel):
    radius_km: int = SEARCH_RADIUS_KM
    # From OpenStreetMap, closest first.
    masjids: list[MasjidOut]
    # Masjids this user typed in. They have no location, so no distance.
    typed_by_you: list[MasjidOut]
    credit: str = OSM_CREDIT
    credit_url: str = OSM_CREDIT_URL


@router.get("/masjids/nearby", response_model=NearbyResponse)
def list_nearby_masjids(user: UserDep, db: DbDep, http: HttpDep, now: NowDep) -> NearbyResponse:
    location = read_location(find_settings(db, user.id))
    if location is None:
        raise HTTPException(status_code=409, detail={"message": "Save your address first."})
    nearby = nearby_masjids(db, http, *location, now)
    typed = db.scalars(
        select(Masjid).where(Masjid.created_by_user_id == user.id).order_by(Masjid.name)
    ).all()
    return NearbyResponse(
        masjids=[_masjid_out(n.masjid, n.distance_km) for n in nearby],
        typed_by_you=[_masjid_out(m) for m in typed],
    )


def _optional_text(value: str | None) -> str | None:
    value = " ".join(value.split()) if value else ""
    return value or None


class MainMasjidRequest(BaseModel):
    # masjid: picked from the list. custom: "My masjid isn't listed". home: "I pray at home".
    choice: Literal["masjid", "custom", "home"]
    masjid_id: uuid.UUID | None = None
    name: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=300)
    short_name: str | None = Field(default=None, max_length=40, description='Like "KMA"')


@router.put("/settings/main-masjid", response_model=SaveResponse)
def save_main_masjid(request: MainMasjidRequest, user: UserDep, db: DbDep, http: HttpDep, now: NowDep) -> SaveResponse:
    row = get_settings(db, user.id)
    if request.choice == "home":
        row.main_masjid_choice = "home"
        row.main_masjid_id = None
        row.main_masjid_short_name = None
        return _saved(db, http, user, now)

    if request.choice == "masjid":
        masjid = usable_masjid(db, user.id, request.masjid_id) if request.masjid_id else None
        if masjid is None:
            raise HTTPException(status_code=404, detail={"message": "Pick a masjid from the list."})
    else:
        name, address = _optional_text(request.name), _optional_text(request.address)
        if not name or not address:
            raise HTTPException(status_code=422, detail={"message": "Type the masjid's name and address."})
        # Typing the same masjid again reuses it instead of adding a copy.
        masjid = db.scalars(
            select(Masjid).where(
                Masjid.created_by_user_id == user.id, Masjid.name == name, Masjid.address == address
            )
        ).first()
        if masjid is None:
            masjid = Masjid(source="user", name=name, address=address, created_by_user_id=user.id)
            db.add(masjid)
            db.flush()

    row.main_masjid_choice = "masjid"
    row.main_masjid_id = masjid.id
    row.main_masjid_short_name = _optional_text(request.short_name)
    return _saved(db, http, user, now)


# ---- Step 4: weekly grid ----


class WeeklyRequest(BaseModel):
    days: list[WeekdayPrayers] = Field(min_length=7, max_length=7)

    @field_validator("days")
    @classmethod
    def one_of_each_day(cls, days: list[WeekdayPrayers]) -> list[WeekdayPrayers]:
        if sorted(d.weekday for d in days) != list(range(7)):
            raise ValueError("Send each weekday, Monday (0) to Sunday (6), once.")
        return days


@router.put("/settings/weekly", response_model=SaveResponse)
def save_weekly(request: WeeklyRequest, user: UserDep, db: DbDep, http: HttpDep, now: NowDep) -> SaveResponse:
    saved = {d.weekday: d for d in weekly_rows(db, user.id)}
    for day in request.days:
        row = saved.get(day.weekday)
        if row is None:
            row = WeeklyMasjidPrayers(user_id=user.id, weekday=day.weekday)
            db.add(row)
        for prayer in PRAYERS:
            setattr(row, prayer, getattr(day, prayer))
    return _saved(db, http, user, now)


# ---- Step 5: Jumuah masjids ----


class JumuahRequest(BaseModel):
    # Empty is allowed: Jumuah isn't required of everyone.
    masjid_ids: list[uuid.UUID] = Field(max_length=10)


@router.put("/settings/jumuah", response_model=SaveResponse)
def save_jumuah(request: JumuahRequest, user: UserDep, db: DbDep, http: HttpDep, now: NowDep) -> SaveResponse:
    ids = list(dict.fromkeys(request.masjid_ids))  # drop repeats, keep order
    for masjid_id in ids:
        if usable_masjid(db, user.id, masjid_id) is None:
            raise HTTPException(status_code=404, detail={"message": "Pick Jumuah masjids from the list."})
    db.execute(delete(UserJumuahMasjid).where(UserJumuahMasjid.user_id == user.id))
    db.add_all(UserJumuahMasjid(user_id=user.id, masjid_id=masjid_id) for masjid_id in ids)
    get_settings(db, user.id).jumuah_saved = True
    return _saved(db, http, user, now)


# ---- Finishing setup, and retrying Google ----


@router.post("/setup/finish", response_model=SaveResponse)
def finish_setup(user: UserDep, db: DbDep, http: HttpDep, now: NowDep) -> SaveResponse:
    """Mark setup done and fill the Prayers calendar with the next 14 days."""
    row = get_settings(db, user.id)
    missing = missing_steps(db, row)
    if missing:
        raise HTTPException(
            status_code=409, detail={"message": "Some setup questions aren't answered yet.", "missing": missing}
        )
    if row.setup_completed_at is None:
        row.setup_completed_at = now
    return _saved(db, http, user, now)


@router.post("/calendar/sync", response_model=CalendarUpdate)
def sync_calendar(user: UserDep, db: DbDep, http: HttpDep, now: NowDep) -> CalendarUpdate:
    """Send anything still waiting. Safe to press as often as you like."""
    return update_calendar(db, http, user.id, now)
