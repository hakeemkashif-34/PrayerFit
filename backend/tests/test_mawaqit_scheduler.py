"""Reading MAWAQIT: once per masjid every 6 hours, a 24-hour wait after a
block or 3 failures, last good data kept, and update jobs for linked users."""

import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.masjid_times.scheduler import block_start, run_due_fetches, run_fetch
from app.models import MasjidDayTimes, MasjidFetchJob, MasjidSource, UpdateJob
from tests.masjid_helpers import add_user, link, masjid_id
from tests.mawaqit_pages import conf, page, set_day

TORONTO = ZoneInfo("America/Toronto")
NOW = datetime(2026, 10, 25, 13, 0, tzinfo=TORONTO)  # 17:00 UTC, in the 12:00 block


@pytest.fixture
def kma(db, fake_google, fake_mawaqit):
    """3 users who pray at KMA, which is linked to MAWAQIT."""
    for sub in ("user-a", "user-b", "user-c"):
        add_user(fake_google, db, sub, masjid_name="KMA", at_masjid={0: {"isha"}})
    kma = masjid_id(db, "KMA")
    link(db, kma, "kma-kanata", fake_mawaqit)
    return kma


def source(db, masjid) -> MasjidSource:
    with Session(db) as session:
        return session.get(MasjidSource, masjid)


def isha_iqamah(db, masjid, day: date) -> time | None:
    with Session(db) as session:
        row = session.scalars(
            select(MasjidDayTimes).where(MasjidDayTimes.masjid_id == masjid, MasjidDayTimes.local_date == day)
        ).first()
        return row.isha_iqamah if row else None


def queued(db) -> set[str]:
    with Session(db) as session:
        return {j.id for j in session.scalars(select(UpdateJob).where(UpdateJob.status == "pending"))}


def test_blocks_are_6_hours():
    assert block_start(NOW).hour == 12
    assert block_start(NOW.replace(hour=1)).hour == 0  # 05:00 UTC


def test_one_fetch_per_masjid_not_per_user(db, http, kma, fake_mawaqit):
    results = run_due_fetches(db, http, NOW)
    assert [r.status for r in results] == ["done"]
    assert len(fake_mawaqit.requests) == 1
    assert str(fake_mawaqit.requests[0].url) == "https://mawaqit.net/en/kma-kanata"
    with Session(db) as session:
        assert session.scalars(select(MasjidDayTimes).where(MasjidDayTimes.masjid_id == kma)).all()
        rows = session.scalars(select(MasjidDayTimes)).all()
    assert len(rows) == 30
    assert {r.source for r in rows} == {"mawaqit"}
    assert rows[0].fetched_at == NOW


def test_at_most_once_every_6_hours(db, http, kma, fake_mawaqit):
    run_due_fetches(db, http, NOW)  # 17:00 UTC, the 12:00 block
    run_due_fetches(db, http, NOW + timedelta(minutes=59))  # 17:59 UTC, same block
    assert len(fake_mawaqit.requests) == 1
    run_due_fetches(db, http, NOW + timedelta(hours=1))  # 18:00 UTC, a new block
    run_due_fetches(db, http, NOW + timedelta(hours=6, minutes=59))  # 23:59 UTC, same block
    assert len(fake_mawaqit.requests) == 2


def test_a_masjid_nobody_uses_is_never_fetched(db, http, fake_mawaqit):
    from tests.masjid_helpers import add_masjid

    unused = add_masjid(db, "Nobody's Masjid")
    link(db, unused, "nobody", fake_mawaqit)
    assert run_due_fetches(db, http, NOW) == []
    assert fake_mawaqit.requests == []


@pytest.mark.parametrize("status", [403, 429])
def test_403_and_429_wait_24_hours(db, http, kma, fake_mawaqit, status):
    fake_mawaqit.failure = status
    assert [r.status for r in run_due_fetches(db, http, NOW)] == ["blocked"]
    assert source(db, kma).retry_after == NOW + timedelta(hours=24)
    fake_mawaqit.failure = None
    for hours in (6, 12, 18, 23):
        run_due_fetches(db, http, NOW + timedelta(hours=hours))
    assert len(fake_mawaqit.requests) == 1
    assert [r.status for r in run_due_fetches(db, http, NOW + timedelta(hours=24))] == ["done"]
    assert source(db, kma).consecutive_failures == 0


def test_3_failures_in_a_row_wait_24_hours(db, http, kma, fake_mawaqit):
    fake_mawaqit.failure = 500
    assert run_due_fetches(db, http, NOW)[0].status == "failed"
    fake_mawaqit.failure = "timeout"
    assert run_due_fetches(db, http, NOW + timedelta(hours=6))[0].status == "failed"
    fake_mawaqit.failure = None
    fake_mawaqit.pages["kma-kanata"] = "<html>The page changed</html>"
    assert run_due_fetches(db, http, NOW + timedelta(hours=12))[0].status == "blocked"
    third = NOW + timedelta(hours=12)
    assert source(db, kma).retry_after == third + timedelta(hours=24)
    assert run_due_fetches(db, http, NOW + timedelta(hours=18)) == []
    assert len(fake_mawaqit.requests) == 3


def test_a_success_resets_the_failure_count(db, http, kma, fake_mawaqit):
    fake_mawaqit.failure = 500
    run_due_fetches(db, http, NOW)
    run_due_fetches(db, http, NOW + timedelta(hours=6))
    fake_mawaqit.failure = None
    run_due_fetches(db, http, NOW + timedelta(hours=12))
    assert source(db, kma).consecutive_failures == 0
    assert source(db, kma).retry_after is None


def test_a_broken_page_keeps_the_last_good_data(db, http, kma, fake_mawaqit):
    run_due_fetches(db, http, NOW)
    good = source(db, kma).last_success_at
    assert isha_iqamah(db, kma, date(2026, 10, 26)) == time(20, 15)

    # Isha iqamah 2 hours after adhan: impossible, so nothing from this page is used.
    fake_mawaqit.pages["kma-kanata"] = page(
        set_day(conf(), 10, 27, iqamah=["+20", "13:00", "+10", "+5", "21:45"])
    )
    later = NOW + timedelta(hours=6)
    assert run_due_fetches(db, http, later)[0].status == "failed"
    assert isha_iqamah(db, kma, date(2026, 10, 26)) == time(20, 15)
    assert source(db, kma).last_success_at == good
    assert "more than 90 minutes" in source(db, kma).last_error


def test_a_page_that_is_too_big_is_refused(db, http, kma, fake_mawaqit):
    fake_mawaqit.failure = "huge"
    result = run_due_fetches(db, http, NOW)[0]
    assert result.status == "failed"
    assert "3 MB" in result.message


def test_failures_are_logged_without_addresses(db, http, kma, fake_mawaqit, caplog):
    fake_mawaqit.pages["kma-kanata"] = "<html>no data</html>"
    with caplog.at_level(logging.INFO):
        run_due_fetches(db, http, NOW)
    text = caplog.text
    assert f"MAWAQIT fetch for masjid {kma} failed: MAWAQIT page has no confData" in text
    assert "Test Street" not in text and "Masjid Road" not in text and "45.4" not in text


def test_a_change_queues_updates_only_for_linked_users(db, http, kma, fake_google, fake_mawaqit):
    # user-e prays at another masjid, so KMA has nothing to do with them. Jumuah is at the main masjid too.
    add_user(fake_google, db, "user-e", masjid_name="Other Masjid", at_masjid={0: {"isha"}})
    from tests.masjid_helpers import user_id

    run_due_fetches(db, http, NOW)
    linked = {f"update:{user_id(db, s)}" for s in ("user-a", "user-b", "user-c")}
    assert queued(db) == linked

    # The same times again: nothing new to queue.
    with Session(db) as session:
        for job in session.scalars(select(UpdateJob)):
            job.status = "done"
        session.commit()
    run_due_fetches(db, http, NOW + timedelta(hours=6))
    assert queued(db) == set()

    # KMA moves Isha from 8:15 pm to 8:30 pm.
    fake_mawaqit.pages["kma-kanata"] = page(set_day(conf(), 10, 28, iqamah=["+20", "13:00", "+10", "+5", "20:30"]))
    run_due_fetches(db, http, NOW + timedelta(hours=12))
    assert queued(db) == linked
    assert source(db, kma).last_changed_at == NOW + timedelta(hours=12)


def test_force_fetches_again_in_the_same_block(db, http, kma, fake_mawaqit):
    with Session(db, expire_on_commit=False) as session:
        assert run_fetch(session, http, kma, NOW).status == "done"
        assert run_fetch(session, http, kma, NOW).status == "skipped"
        assert run_fetch(session, http, kma, NOW, force=True).status == "done"
    assert len(fake_mawaqit.requests) == 2


def test_the_job_id_is_stable(db, http, kma):
    run_due_fetches(db, http, NOW)
    run_due_fetches(db, http, NOW + timedelta(minutes=30))
    with Session(db) as session:
        ids = [j.id for j in session.scalars(select(MasjidFetchJob))]
    assert ids == [f"mawaqit:{kma}:2026-10-25T12"]


def test_a_new_day_at_the_end_isnt_a_change(db, http, kma):
    run_due_fetches(db, http, NOW)
    with Session(db) as session:
        session.execute(UpdateJob.__table__.delete())
        session.commit()
    # A day later the page covers one more date, but no saved time changed.
    assert run_due_fetches(db, http, NOW + timedelta(days=1))[0].changed is False
    assert queued(db) == set()
    assert source(db, kma).last_changed_at == NOW
