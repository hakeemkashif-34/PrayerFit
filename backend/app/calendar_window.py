"""Keep the next 14 days of prayers in the user's Prayers calendar.

1. Work out every event for today and the next 13 days from the saved
   setup, the masjid's published times, and the drive times (event_plan.py).
2. Save each one in prayer_events. New rows are added. Future rows are
   updated. Rows that already started are left alone.
3. A row only goes back to "pending" if what Google would get changed
   (see event_hash). So Google only gets the events that changed.
4. A future drive block that's no longer needed (the prayer moved home,
   or the drive time became unknown) is marked "delete_pending". That's
   the only kind of event the app ever deletes.
5. Send the pending rows to Google, using the duplicate-proof code in
   prayer_sync.py.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx2
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.tokens import get_access_token
from app.busy_times import busy_on
from app.drive_times import drive_seconds
from app.geo.timezones import masjid_time_zone
from app.event_plan import MasjidContext, PlannedEvent, drive_event_id, plan_day
from app.google_calendar import GoogleCalendar
from app.locks import advisory_lock
from app.masjid_times.source import next_friday
from app.masjid_times.store import load_masjid_times
from app.models import Masjid, PrayerEvent
from app.prayer_sync import PRAYERS, event_hash, send_to_google
from app.prayer_times import calculate_prayer_times
from app.prayers_calendar import ensure_prayers_calendar
from app.user_settings import Setup, load_setup

WINDOW_DAYS = 14
# Drive blocks first, so a day reads in order: drive, then prayer.
KIND_ORDER = {"drive": 0, "prayer": 1}


class SetupIncomplete(Exception):
    """The user hasn't finished setup, so there's nothing to put in the calendar."""


def window_dates(first_day: date, days: int = WINDOW_DAYS) -> list[date]:
    # Adding days to a date moves the calendar date. It never adds 24 hours,
    # so a daylight saving change can't skip or repeat a day.
    return [first_day + timedelta(days=n) for n in range(days)]


def rows_for_dates(db: Session, user_id: uuid.UUID, dates: list[date]) -> list[PrayerEvent]:
    rows = db.scalars(
        select(PrayerEvent).where(PrayerEvent.user_id == user_id, PrayerEvent.local_date.in_(dates))
    ).all()
    return sorted(rows, key=lambda r: (r.local_date, PRAYERS.index(r.prayer), KIND_ORDER.get(r.kind, 1)))


@dataclass(frozen=True)
class MasjidInputs:
    """The user's masjids, their published times, and the drive times, for plan_day."""

    main: MasjidContext | None
    jumuah: list[MasjidContext]


def masjid_inputs(db: Session, http: httpx2.Client, setup: Setup, dates: list[date], now: datetime) -> MasjidInputs:
    masjids: list[Masjid] = []
    for masjid in ([setup.masjid] if setup.masjid else []) + list(setup.jumuah_masjids):
        if all(m.id != masjid.id for m in masjids):
            masjids.append(masjid)
    times = load_masjid_times(db, [m.id for m in masjids], dates, now)
    drives = drive_seconds(db, http, setup.user_id, (setup.latitude, setup.longitude), masjids, now)

    def context(masjid: Masjid) -> MasjidContext:
        return MasjidContext(
            masjid=masjid,
            label=setup.label_for(masjid),
            time_zone=masjid_time_zone(masjid),
            times=times.get(masjid.id),
            drive_seconds=drives.get(masjid.id),
            jumuah_minutes=masjid.jumuah_minutes,
        )

    return MasjidInputs(
        main=context(setup.masjid) if setup.masjid else None,
        jumuah=[context(m) for m in setup.jumuah_masjids],
    )


def plan_window(
    setup: Setup, dates: list[date], inputs: MasjidInputs, busy: list[tuple[datetime, datetime]] | None = None
) -> list[PlannedEvent]:
    # MAWAQIT's Jumuah times are only for this one Friday (today, if it's Friday).
    upcoming_friday = next_friday(dates[0])
    planned = []
    for local_date in dates:
        day = calculate_prayer_times(
            setup.latitude, setup.longitude, local_date, setup.time_zone, setup.method, setup.asr_method
        )
        planned.extend(plan_day(setup, local_date, day, inputs.main, inputs.jumuah, busy, upcoming_friday))
    return planned


def _insert(db: Session, user_id: uuid.UUID, planned: PlannedEvent, row_id: uuid.UUID) -> None:
    # DO NOTHING: if another run added it a moment ago, keep theirs.
    db.execute(
        insert(PrayerEvent)
        .values(
            id=row_id,
            user_id=user_id,
            local_date=planned.local_date,
            prayer=planned.prayer,
            kind=planned.kind,
            sync_status="pending",
            **planned.values(),
        )
        .on_conflict_do_nothing(index_elements=["user_id", "local_date", "prayer", "kind"])
    )


def _update(row: PrayerEvent, planned: PlannedEvent) -> None:
    for key, value in planned.values().items():
        setattr(row, key, value)
    if row.sync_status == "deleted":
        row.sync_status = "pending"  # needed again, so it goes back to Google
    elif event_hash(row) != row.synced_hash:
        row.sync_status = "pending"
    elif row.sync_status == "delete_pending":
        row.sync_status = "synced"  # needed again before it was deleted, and Google has it as it is


def _drop_drive_block(row: PrayerEvent) -> None:
    if row.sync_status in ("delete_pending", "deleted"):
        return
    # Never reached Google: there's nothing to delete there.
    row.sync_status = "delete_pending" if row.google_calendar_id is not None else "deleted"


def save_window(db: Session, user_id: uuid.UUID, planned: list[PlannedEvent], dates: list[date], now: datetime) -> None:
    """Save the planned events. Only changed future rows become pending. Commits."""
    existing = {(r.local_date, r.prayer, r.kind): r for r in rows_for_dates(db, user_id, dates)}

    # 1. Prayer blocks.
    for event in (p for p in planned if p.kind == "prayer"):
        row = existing.get((event.local_date, event.prayer, "prayer"))
        if row is None:
            _insert(db, user_id, event, uuid.uuid4())
        elif row.starts_at > now:  # already started means it's the past. Leave it alone.
            _update(row, event)
    db.flush()

    # 2. Drive blocks. Each one's ID comes from its prayer event's ID.
    prayer_ids = {
        (r.local_date, r.prayer): r.id for r in rows_for_dates(db, user_id, dates) if r.kind == "prayer"
    }
    wanted = {(p.local_date, p.prayer): p for p in planned if p.kind == "drive"}
    for key, event in wanted.items():
        row = existing.get((*key, "drive"))
        if row is None:
            if event.starts_at > now:  # no point adding a drive that has already started
                _insert(db, user_id, event, drive_event_id(prayer_ids[key]))
        elif row.starts_at > now:
            _update(row, event)
    for (local_date, prayer, kind), row in existing.items():
        if kind == "drive" and (local_date, prayer) not in wanted and row.starts_at > now:
            _drop_drive_block(row)
    db.commit()


def user_lock(db: Session, user_id: uuid.UUID):
    """Only one calendar update per user at a time.

    The website, the nightly job, and queued updates could all update the
    same user at once. The advisory lock makes the others wait.
    """
    return advisory_lock(db, f"calendar:{user_id}")


@dataclass
class RefreshResult:
    rows: list[PrayerEvent]  # every row in the window, except deleted drive blocks
    sent: int  # how many went to Google


def refresh_calendar(
    db: Session,
    http: httpx2.Client,
    user_id: uuid.UUID,
    now: datetime,
    days: int = WINDOW_DAYS,
    first_day: date | None = None,
) -> RefreshResult:
    """Bring the user's calendar up to date for today plus days - 1.

    Raises SetupIncomplete, ReauthRequired, CalendarAccessMissing, or
    SyncIncomplete (Google failed partway; the rest stay pending).
    """
    with user_lock(db, user_id):
        setup = load_setup(db, user_id)
        if setup is None:
            raise SetupIncomplete()
        if first_day is None:
            first_day = now.astimezone(ZoneInfo(setup.time_zone)).date()
        dates = window_dates(first_day, days)
        inputs = masjid_inputs(db, http, setup, dates, now)
        # Busy times are only needed for Jumuah, and only the coming Friday
        # has Jumuah times. One free/busy call, nothing saved.
        friday = next_friday(dates[0])
        busy = (
            busy_on(db, http, user_id, friday, setup.time_zone).busy
            if setup.jumuah_masjids and friday in dates
            else []
        )
        save_window(db, user_id, plan_window(setup, dates, inputs, busy), dates, now)

        # Get (or refresh) the token first, so a dead sign-in is reported
        # before any Google call. The rows above stay saved either way.
        get_access_token(db, http, user_id)
        calendar = GoogleCalendar(http, lambda force: get_access_token(db, http, user_id, force))
        prayers_calendar = ensure_prayers_calendar(db, calendar, user_id, setup.time_zone)

        # Read again: a recreated calendar marks every row pending.
        rows = rows_for_dates(db, user_id, dates)
        waiting = [r for r in rows if r.sync_status in ("pending", "delete_pending")]
        send_to_google(db, calendar, prayers_calendar.google_calendar_id, waiting, now)
        return RefreshResult(rows=[r for r in rows if r.sync_status != "deleted"], sent=len(waiting))
