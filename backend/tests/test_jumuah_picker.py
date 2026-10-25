"""The Jumuah picker: shortest drive, then earliest slot, around busy times."""

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.jumuah import JumuahSlot, pick_jumuah

TORONTO = ZoneInfo("America/Toronto")
KMA, STITTSVILLE, JAMIA = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
LISTED = [STITTSVILLE, JAMIA, KMA]


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 30, hour, minute, tzinfo=TORONTO)


SLOTS = [
    JumuahSlot(KMA, at(13, 30)),
    JumuahSlot(KMA, at(14, 30)),
    JumuahSlot(STITTSVILLE, at(13, 15)),
    JumuahSlot(JAMIA, at(13, 0)),
]
DRIVES = {KMA: 5 * 60, STITTSVILLE: 12 * 60, JAMIA: 20 * 60}


def test_shortest_drive_wins():
    choice = pick_jumuah(SLOTS, DRIVES, 0, [], LISTED)
    assert choice.slot == JumuahSlot(KMA, at(13, 30))
    assert choice.trip.leave_at == at(13, 25)
    assert "Shortest drive" in choice.reason and "5 min" in choice.reason


def test_ties_are_broken_by_the_earliest_slot():
    drives = {KMA: 600, STITTSVILLE: 600, JAMIA: 1200}
    assert pick_jumuah(SLOTS, drives, 0, [], LISTED).slot == JumuahSlot(STITTSVILLE, at(13, 15))
    # The same masjid: its earliest slot.
    only_kma = [s for s in SLOTS if s.masjid_id == KMA]
    assert pick_jumuah(only_kma, DRIVES, 0, [], LISTED).slot.starts_at == at(13, 30)


def test_busy_times_remove_slots():
    busy = [(at(13, 0), at(13, 45))]  # clashes with KMA 1:30 and Stittsville 1:15 and Jamia 1:00
    choice = pick_jumuah(SLOTS, DRIVES, 0, busy, LISTED)
    assert choice.slot == JumuahSlot(KMA, at(14, 30))
    assert "clash" in choice.reason


def test_a_busy_drive_removes_the_slot_too():
    # The prayer is free, but the 5 minute drive to KMA's 1:30 starts at 1:25.
    busy = [(at(13, 20), at(13, 26))]
    only_kma = [s for s in SLOTS if s.masjid_id == KMA]
    assert pick_jumuah(only_kma, DRIVES, 0, busy, LISTED).slot.starts_at == at(14, 30)
    # Arriving 10 minutes early means leaving at 1:15, so a 1:12 to 1:14 errand still fits.
    busy = [(at(13, 12), at(13, 14))]
    assert pick_jumuah(only_kma, DRIVES, 10, busy, LISTED).slot.starts_at == at(13, 30)
    # But 1:14 to 1:16 overlaps the drive.
    busy = [(at(13, 14), at(13, 16))]
    assert pick_jumuah(only_kma, DRIVES, 10, busy, LISTED).slot.starts_at == at(14, 30)


def test_unknown_drive_times_use_the_listed_order():
    unknown = {KMA: None, STITTSVILLE: None, JAMIA: None}
    choice = pick_jumuah(SLOTS, unknown, 0, [], LISTED)
    assert choice.slot == JumuahSlot(STITTSVILLE, at(13, 15))
    assert choice.trip.leave_at is None
    assert "first masjid in your Jumuah list" in choice.reason
    assert pick_jumuah(SLOTS, {}, 0, [], [JAMIA, KMA]).slot.masjid_id == JAMIA


def test_known_drive_times_come_before_unknown_ones():
    drives = {KMA: None, STITTSVILLE: None, JAMIA: 1500}
    assert pick_jumuah(SLOTS, drives, 0, [], LISTED).slot.masjid_id == JAMIA


def test_no_slots():
    choice = pick_jumuah([], DRIVES, 0, [], LISTED)
    assert choice.slot is None
    assert "have Jumuah times" in choice.reason


def test_every_slot_busy():
    choice = pick_jumuah(SLOTS, DRIVES, 0, [(at(12, 0), at(16, 0))], LISTED)
    assert choice.slot is None
    assert "clashes" in choice.reason


def test_no_jumuah_masjids():
    # A user with no Jumuah masjids has no slots and no listed order.
    assert pick_jumuah([], {}, 0, [], []).slot is None


def test_leave_time_is_rounded_down_to_the_minute():
    choice = pick_jumuah([JumuahSlot(KMA, at(13, 30))], {KMA: 13 * 60 + 30}, 5, [], [KMA])
    assert choice.trip.arrive_at == at(13, 25)
    assert choice.trip.leave_at == at(13, 11)  # 13:25 - 13.5 min = 13:11:30, rounded down
    assert choice.trip.leave_at.second == 0
    assert choice.trip.target - choice.trip.arrive_at == timedelta(minutes=5)


def test_the_whole_60_minute_jumuah_has_to_be_free():
    # 2:00 to 2:10 pm is after a 1:30 start, but inside its 60 minute block.
    only_kma = [s for s in SLOTS if s.masjid_id == KMA]
    choice = pick_jumuah(only_kma, DRIVES, 0, [(at(14, 0), at(14, 10))], LISTED)
    assert choice.slot.starts_at == at(14, 30)
    # Busy from 2:30 pm, right when the 1:30 block ends: 1:30 still fits, and
    # it's the only one, since the 2:30 slot clashes.
    choice = pick_jumuah(only_kma, DRIVES, 0, [(at(14, 30), at(14, 40))], LISTED)
    assert choice.slot.starts_at == at(13, 30)
    assert "Other times clash" in choice.reason
