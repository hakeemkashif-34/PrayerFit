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
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.sessions import current_user
from app.calendar_window import SetupIncomplete
from app.clock import get_now
from app.db import get_db
from app.geo.distance import distance_km
from app.geo.photon import MAX_SUGGESTIONS, MIN_QUERY_LENGTH, Suggestion, suggest, suggest_masjids
from app.geo.timezones import timezone_for
from app.google_errors import CalendarAccessMissing, GoogleError, ReauthRequired
from app.http_client import get_http
from app.event_plan import date_text
from app.masjid_times.freshness import Freshness, freshness
from app.models import Masjid, MasjidSource, PrayerEvent, User, UserJumuahMasjid, WeeklyMasjidPrayers
from app.prayer_sync import SyncIncomplete
from app.prayer_times import DEFAULT_TIMEZONE, AsrMethod, CalculationMethod
from app.update_jobs import queue_update, run_update
from app.user_settings import (
    PRAYERS,
    DEFAULT_ARRIVE_EARLY_MINUTES,
    DEFAULT_COLOR_ID,
    find_settings,
    follow_main_masjid,
    asr_method_of,
    get_settings,
    jumuah_masjids,
    method_of,
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
# Google Calendar's fixed event colours. The website shows their names and swatches.
ColorId = Literal["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"]

UserDep = Annotated[User, Depends(current_user)]
DbDep = Annotated[Session, Depends(get_db)]
HttpDep = Annotated[httpx2.Client, Depends(get_http)]
NowDep = Annotated[datetime, Depends(get_now)]


# ---- What the website gets back ----


class MasjidOut(BaseModel):
    id: uuid.UUID
    # Empty for a masjid picked by its address.
    name: str | None
    address: str | None
    # "openstreetmap", or "user" (picked by its address)
    source: str
    distance_km: float | None = None
    # Where this masjid's times come from, like "Times from MAWAQIT, updated Oct 25, 2026".
    iqamah_status: str


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
    # Setup questions not answered yet, in order: address, masjid, weekly, optional.
    missing: list[str]
    address: str | None
    place_name: str | None
    time_zone: str | None
    # The defaults (ISNA, standard) until the user picks others.
    method: CalculationMethod
    asr_method: AsrMethod
    main_masjid_choice: Literal["masjid", "home"] | None
    main_masjid: MasjidOut | None
    main_masjid_short_name: str | None
    weekly: list[WeekdayPrayers]
    jumuah_saved: bool
    # In the order the user listed them.
    jumuah_masjids: list[MasjidOut]
    # The optional step: minutes to arrive before iqamah, and Google colour IDs.
    arrive_early_minutes: int
    prayer_color_id: ColorId | None
    drive_color_id: ColorId | None


class CalendarUpdate(BaseModel):
    status: Literal["updated", "waiting", "sign_in_needed", "not_set_up"]
    sent: int = 0
    waiting: int = 0
    message: str


class SaveResponse(BaseModel):
    settings: SettingsOut
    # Empty during setup, when nothing goes to Google yet.
    calendar: CalendarUpdate | None = None


def times_status(db: Session, masjid: Masjid, now: datetime, time_zone: str) -> str:
    """Where this masjid's times come from, in words."""
    source = db.get(MasjidSource, masjid.id)
    if source is None:
        return "Not linked to MAWAQIT, so calculated times are used"
    age = freshness(source.last_success_at, now)
    if age is Freshness.NEVER:
        return "Linked to MAWAQIT. Its times haven't been read yet"
    if age is Freshness.TOO_OLD:
        return "MAWAQIT times are more than 7 days old, so calculated times are used"
    if age is Freshness.STALE:
        return f"MAWAQIT times may be out of date (last updated {date_text(source.last_success_at, time_zone)})"
    changed = source.last_changed_at or source.last_success_at
    return f"Times from MAWAQIT, updated {date_text(changed, time_zone)}"


def _masjid_out(db: Session, masjid: Masjid, home: tuple[float, float] | None, now: datetime, time_zone: str) -> MasjidOut:
    """A masjid, with its straight-line distance from home when both locations are known."""
    distance = None
    if home is not None and masjid.latitude is not None and masjid.longitude is not None:
        distance = round(distance_km(*home, masjid.latitude, masjid.longitude), 1)
    return MasjidOut(
        id=masjid.id, name=masjid.name, address=masjid.address, source=masjid.source, distance_km=distance,
        iqamah_status=times_status(db, masjid, now, time_zone),
    )


def settings_out(db: Session, user_id: uuid.UUID, now: datetime) -> SettingsOut:
    row = find_settings(db, user_id)
    zone = row.time_zone or DEFAULT_TIMEZONE
    home = read_location(row)
    main = db.get(Masjid, row.main_masjid_id) if row.main_masjid_id else None
    missing = missing_steps(db, row)
    return SettingsOut(
        setup_complete=row.setup_completed_at is not None and not missing,
        missing=missing,
        address=read_address(row),
        place_name=read_place_name(row),
        time_zone=row.time_zone,
        method=method_of(row),
        asr_method=asr_method_of(row),
        main_masjid_choice=row.main_masjid_choice,
        main_masjid=_masjid_out(db, main, home, now, zone) if main and row.main_masjid_choice == "masjid" else None,
        main_masjid_short_name=row.main_masjid_short_name,
        weekly=[
            WeekdayPrayers(weekday=d.weekday, **{p: getattr(d, p) for p in PRAYERS})
            for d in weekly_rows(db, user_id)
        ],
        jumuah_saved=row.jumuah_saved,
        jumuah_masjids=[_masjid_out(db, m, home, now, zone) for m in jumuah_masjids(db, user_id)],
        arrive_early_minutes=row.arrive_early_minutes or 0,
        prayer_color_id=row.prayer_color_id,
        drive_color_id=row.drive_color_id,
    )


def _pending_count(db: Session, user_id: uuid.UUID) -> int:
    return len(
        db.scalars(
            select(PrayerEvent.id).where(
                PrayerEvent.user_id == user_id, PrayerEvent.sync_status == "pending"
            )
        ).all()
    )


def update_calendar(db: Session, http: httpx2.Client, user_id: uuid.UUID, now: datetime, reason: str = "settings") -> CalendarUpdate:
    """Queue an update job, run it straight away, and say how it went.

    Settings are already saved by now. Going through the job (with its
    stable ID "update:{user_id}") means a failure here is retried by the
    worker, and two saves in a row can't run two updates at once.
    """
    queue_update(db, user_id, reason, now)
    db.commit()
    try:
        result = run_update(db, http, user_id, now)
        if result is None:
            return CalendarUpdate(
                status="waiting",
                message="Saved. Your calendar is already updating, and it will include this change.",
            )
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


def _saved(db: Session, http: httpx2.Client, user: User, now: datetime, reason: str = "settings") -> SaveResponse:
    """Commit, then update the calendar if setup is already finished."""
    db.commit()
    row = get_settings(db, user.id)
    calendar = update_calendar(db, http, user.id, now, reason) if row.setup_completed_at else None
    return SaveResponse(settings=settings_out(db, user.id, now), calendar=calendar)


# ---- Reading ----


@router.get("/settings", response_model=SettingsOut)
def read_settings(user: UserDep, db: DbDep, now: NowDep) -> SettingsOut:
    """Your saved setup answers. Only ever your own."""
    return settings_out(db, user.id, now)


# ---- Question 1: location ----


def _one_line(value: str) -> str:
    return " ".join(value.split())


class SuggestRequest(BaseModel):
    # In the body, never the URL, so it can't end up in access logs.
    query: str = Field(max_length=200)

    @field_validator("query")
    @classmethod
    def strip(cls, value: str) -> str:
        return _one_line(value)


class LocationSuggestion(BaseModel):
    # Its place in the list. The website sends it back to pick this one.
    index: int
    label: str


class SuggestResponse(BaseModel):
    suggestions: list[LocationSuggestion]
    credit: str = OSM_CREDIT
    credit_url: str = OSM_CREDIT_URL


@router.post("/setup/location/suggest", response_model=SuggestResponse)
def suggest_locations(request: SuggestRequest, user: UserDep, db: DbDep, http: HttpDep, now: NowDep) -> SuggestResponse:
    """Up to 5 places for what the user has typed so far. Saves nothing.

    The website waits until the user stops typing for about 400 ms. Fewer
    than 3 characters gets an empty list without calling Photon.
    """
    found = suggest(db, http, request.query, now)
    return SuggestResponse(
        suggestions=[LocationSuggestion(index=i, label=s.label) for i, s in enumerate(found)]
    )


class LocationRequest(BaseModel):
    query: str = Field(min_length=MIN_QUERY_LENGTH, max_length=200)
    index: int = Field(ge=0, lt=MAX_SUGGESTIONS)

    @field_validator("query")
    @classmethod
    def strip(cls, value: str) -> str:
        return _one_line(value)


@router.put("/settings/location", response_model=SaveResponse)
def save_location_choice(request: LocationRequest, user: UserDep, db: DbDep, http: HttpDep, now: NowDep) -> SaveResponse:
    """Save the suggestion the user picked.

    The location comes from the same search the user just saw (it's
    cached), not from the browser, so it always matches what they picked.
    """
    found = suggest(db, http, request.query, now)
    if request.index >= len(found):
        raise HTTPException(
            status_code=404, detail={"message": "That place isn't in the list any more. Search again."}
        )
    place = found[request.index]
    save_location(
        get_settings(db, user.id),
        place.label,
        place.latitude,
        place.longitude,
        timezone_for(place.latitude, place.longitude),
    )
    return _saved(db, http, user, now)


# ---- Calculation method and Asr method (settings page only, for now) ----


class MethodsRequest(BaseModel):
    method: CalculationMethod = CalculationMethod.ISNA
    asr_method: AsrMethod = AsrMethod.STANDARD


@router.put("/settings/methods", response_model=SaveResponse)
def save_methods(request: MethodsRequest, user: UserDep, db: DbDep, http: HttpDep, now: NowDep) -> SaveResponse:
    row = get_settings(db, user.id)
    row.method = request.method.value
    row.asr_method = request.asr_method.value
    return _saved(db, http, user, now)


# ---- Question 2: main masjid ----


def _home(db: Session, user_id: uuid.UUID) -> tuple[float, float]:
    home = read_location(find_settings(db, user_id))
    if home is None:
        raise HTTPException(status_code=409, detail={"message": "Save your location first."})
    return home


class MasjidSuggestion(BaseModel):
    # Its place in the list. The website sends it back to pick this one.
    index: int
    # "masjid" (a place of worship on OpenStreetMap) or "address"
    kind: str
    label: str
    # The address part for a masjid, like "351 Sandhill Road, Ottawa".
    detail: str | None
    distance_km: float


class MasjidSuggestResponse(BaseModel):
    suggestions: list[MasjidSuggestion]


@router.post("/setup/masjid/suggest", response_model=MasjidSuggestResponse)
def suggest_masjid(request: SuggestRequest, user: UserDep, db: DbDep, http: HttpDep, now: NowDep) -> MasjidSuggestResponse:
    """Up to 5 masjids for what the user has typed, closest to home first. Saves nothing.

    If no masjid matches, or the text looks like an address, addresses
    near home are included, so a masjid that isn't on the map can still be picked.
    """
    home = _home(db, user.id)
    found = suggest_masjids(db, http, request.query, home, now)
    return MasjidSuggestResponse(
        suggestions=[
            MasjidSuggestion(
                index=i,
                kind=s.kind,
                label=s.label,
                detail=s.street_address if s.kind == "masjid" else None,
                distance_km=round(distance_km(*home, s.latitude, s.longitude), 1),
            )
            for i, s in enumerate(found)
        ]
    )


class PickRequest(BaseModel):
    query: str = Field(min_length=MIN_QUERY_LENGTH, max_length=200)
    index: int = Field(ge=0, lt=MAX_SUGGESTIONS)

    @field_validator("query")
    @classmethod
    def strip(cls, value: str) -> str:
        return _one_line(value)


def _masjid_from(db: Session, user_id: uuid.UUID, picked: Suggestion) -> Masjid:
    """Find or add the masjid for a picked suggestion. Nothing is made up."""
    if picked.kind == "masjid" and picked.osm_type and picked.osm_id is not None:
        values = {
            "name": picked.name,
            "latitude": picked.latitude,
            "longitude": picked.longitude,
            "address": picked.street_address,
            "updated_at": func.now(),
        }
        masjid_id = db.execute(
            insert(Masjid)
            .values(id=uuid.uuid4(), source="openstreetmap", osm_type=picked.osm_type, osm_id=picked.osm_id, **values)
            .on_conflict_do_update(index_elements=["osm_type", "osm_id"], set_=values)
            .returning(Masjid.id)
        ).scalar_one()
        return db.get(Masjid, masjid_id, populate_existing=True)
    # Picked by its address: private to this user, with no name. Picking
    # the same address again reuses it instead of adding a copy.
    masjid = db.scalars(
        select(Masjid).where(Masjid.created_by_user_id == user_id, Masjid.address == picked.label)
    ).first()
    if masjid is None:
        masjid = Masjid(
            source="user",
            address=picked.label,
            latitude=picked.latitude,
            longitude=picked.longitude,
            created_by_user_id=user_id,
        )
        db.add(masjid)
        db.flush()
    return masjid


@router.post("/masjids/from-suggestion", response_model=MasjidOut)
def masjid_from_suggestion(request: PickRequest, user: UserDep, db: DbDep, http: HttpDep, now: NowDep) -> MasjidOut:
    """Turn a picked suggestion into a saved masjid, so it can be the main masjid or a Jumuah masjid.

    The masjid comes from the same search the user just saw (it's cached),
    not from the browser, so it always matches what they picked.
    """
    home = _home(db, user.id)
    found = suggest_masjids(db, http, request.query, home, now)
    if request.index >= len(found):
        raise HTTPException(
            status_code=404, detail={"message": "That masjid isn't in the list any more. Search again."}
        )
    masjid = _masjid_from(db, user.id, found[request.index])
    db.commit()
    zone = find_settings(db, user.id).time_zone or DEFAULT_TIMEZONE
    return _masjid_out(db, masjid, home, now, zone)


def _optional_text(value: str | None) -> str | None:
    value = " ".join(value.split()) if value else ""
    return value or None


class MainMasjidRequest(BaseModel):
    # masjid: one from POST /masjids/from-suggestion. home: "Skip", every prayer at home.
    # The short name is saved in the optional step now (PUT /settings/optional).
    choice: Literal["masjid", "home"]
    masjid_id: uuid.UUID | None = None


@router.put("/settings/main-masjid", response_model=SaveResponse)
def save_main_masjid(request: MainMasjidRequest, user: UserDep, db: DbDep, http: HttpDep, now: NowDep) -> SaveResponse:
    row = get_settings(db, user.id)
    old_main_id = row.main_masjid_id if row.main_masjid_choice == "masjid" else None
    if request.choice == "home":
        follow_main_masjid(db, row, old_main_id, None)
        row.main_masjid_choice = "home"
        row.main_masjid_id = None
        row.main_masjid_short_name = None
        return _saved(db, http, user, now)

    masjid = usable_masjid(db, user.id, request.masjid_id) if request.masjid_id else None
    if masjid is None:
        raise HTTPException(status_code=404, detail={"message": "Pick a masjid from the suggestions."})
    if row.main_masjid_id != masjid.id:
        # A short name belongs to one masjid. Picking the same one again keeps it.
        row.main_masjid_short_name = None
    follow_main_masjid(db, row, old_main_id, masjid.id)
    row.main_masjid_choice = "masjid"
    row.main_masjid_id = masjid.id
    return _saved(db, http, user, now)


# ---- Question 3: weekly grid ----


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


# ---- Jumuah masjids (settings page only, for now) ----


class JumuahRequest(BaseModel):
    # Empty is allowed: Jumuah isn't required of everyone.
    masjid_ids: list[uuid.UUID] = Field(max_length=10)


@router.put("/settings/jumuah", response_model=SaveResponse)
def save_jumuah(request: JumuahRequest, user: UserDep, db: DbDep, http: HttpDep, now: NowDep) -> SaveResponse:
    ids = list(dict.fromkeys(request.masjid_ids))  # drop repeats, keep order
    for masjid_id in ids:
        if usable_masjid(db, user.id, masjid_id) is None:
            raise HTTPException(status_code=404, detail={"message": "Pick Jumuah masjids from the suggestions."})
    db.execute(delete(UserJumuahMasjid).where(UserJumuahMasjid.user_id == user.id))
    # The order matters: with no drive times, the Jumuah picker uses the first one.
    db.add_all(
        UserJumuahMasjid(user_id=user.id, masjid_id=masjid_id, position=position)
        for position, masjid_id in enumerate(ids)
    )
    get_settings(db, user.id).jumuah_saved = True
    return _saved(db, http, user, now)


# ---- Question 4: optional (can be skipped) ----


class OptionalRequest(BaseModel):
    """A field left out gets its default: 5 minutes early, no short name, and Basil."""

    # strict: a whole number only. 2.5 or "5" is refused, not rounded.
    arrive_early_minutes: int = Field(default=DEFAULT_ARRIVE_EARLY_MINUTES, ge=0, le=30, strict=True)
    # Like "KMA". Only kept when there's a main masjid.
    short_name: str | None = Field(default=None, max_length=40)
    # null uses the Prayers calendar's own colour.
    prayer_color_id: ColorId | None = DEFAULT_COLOR_ID
    drive_color_id: ColorId | None = DEFAULT_COLOR_ID


@router.put("/settings/optional", response_model=SaveResponse)
def save_optional(request: OptionalRequest, user: UserDep, db: DbDep, http: HttpDep, now: NowDep) -> SaveResponse:
    row = get_settings(db, user.id)
    row.arrive_early_minutes = request.arrive_early_minutes
    has_masjid = row.main_masjid_choice == "masjid" and row.main_masjid_id is not None
    row.main_masjid_short_name = _optional_text(request.short_name) if has_masjid else None
    row.prayer_color_id = request.prayer_color_id
    row.drive_color_id = request.drive_color_id
    row.optional_saved = True
    return _saved(db, http, user, now)


# ---- Finishing setup, and retrying Google ----


@router.post("/setup/finish", response_model=SaveResponse)
def finish_setup(user: UserDep, db: DbDep, http: HttpDep, now: NowDep) -> SaveResponse:
    """Mark setup done and fill the Prayers calendar with the next 14 days.

    The website calls this straight after the last question.
    """
    row = get_settings(db, user.id)
    missing = missing_steps(db, row)
    if missing:
        raise HTTPException(
            status_code=409, detail={"message": "Some setup questions aren't answered yet.", "missing": missing}
        )
    if row.setup_completed_at is None:
        row.setup_completed_at = now
    return _saved(db, http, user, now, reason="setup")


@router.post("/calendar/sync", response_model=CalendarUpdate)
def sync_calendar(user: UserDep, db: DbDep, http: HttpDep, now: NowDep) -> CalendarUpdate:
    """Send anything still waiting. Safe to press as often as you like."""
    return update_calendar(db, http, user.id, now, reason="retry")
