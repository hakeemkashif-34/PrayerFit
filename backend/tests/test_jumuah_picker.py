"""The Jumuah picker: the user's pick if it fits, otherwise the earliest that fits."""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from app.jumuah import JumuahPick, JumuahSlot, choose_jumuah, ordinal, slot_windows

TORONTO = ZoneInfo("America/Toronto")
KMA, STITTSVILLE = uuid.uuid4(), uuid.uuid4()
LISTED = [KMA, STITTSVILLE]


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 30, hour, minute, tzinfo=TORONTO)


# KMA: 12:45, 2:00, 2:50 (like its real page). Stittsville: 1:15.
SLOTS = [
    JumuahSlot(KMA, 1, at(12, 45)),
    JumuahSlot(KMA, 2, at(14, 0)),
    JumuahSlot(KMA, 3, at(14, 50)),
    JumuahSlot(STITTSVILLE, 1, at(13, 15)),
]
DRIVES = {KMA: 10 * 60, STITTSVILLE: 20 * 60}
LENGTHS = {KMA: 40, STITTSVILLE: 45}


def choose(pick=None, busy=(), slots=SLOTS, drives=DRIVES, early=5, listed=LISTED):
    return choose_jumuah(list(slots), pick, drives, early, LENGTHS, list(busy), listed)


def chosen(choice) -> tuple:
    return (choice.window.slot.masjid_id, choice.window.slot.order)


def test_the_pick_is_used_when_it_fits():
    choice = choose(pick=JumuahPick(KMA, 2))
    assert chosen(choice) == (KMA, 2)
    assert choice.reason == "Your pick (2nd Jumuah)."


def test_a_clashing_pick_gives_the_earliest_that_fits():
    # Busy 12:30 to 1:00: KMA's 12:45 clashes, and so does the pick (1st).
    choice = choose(pick=JumuahPick(KMA, 1), busy=[(at(12, 30), at(13, 0))])
    assert chosen(choice) == (KMA, 2)  # Stittsville 1:15's drive starts at 12:50, so it clashes too
    assert choice.reason == "Your pick (1st Jumuah) clashes with your calendar, so this is the earliest Jumuah that fits."


def test_the_earliest_that_fits_is_across_all_masjids():
    choice = choose(pick=JumuahPick(KMA, 3), busy=[(at(14, 40), at(15, 0)), (at(12, 30), at(12, 40))])
    assert chosen(choice) == (STITTSVILLE, 1)


def test_every_slot_clashing_gives_the_1st_jumuah_with_a_note():
    choice = choose(pick=JumuahPick(KMA, 2), busy=[(at(12, 0), at(16, 0))])
    assert chosen(choice) == (KMA, 1)
    assert choice.reason == "Every Jumuah clashes with your calendar, so this is the 1st Jumuah."
    assert choice.fit == "clash"


def test_the_1st_jumuah_is_the_earliest_across_all_masjids():
    # Stittsville listed first, but KMA's 12:45 is the earliest of the day.
    choice = choose(pick=JumuahPick(STITTSVILLE, 1), busy=[(at(11, 0), at(16, 0))], listed=[STITTSVILLE, KMA])
    assert chosen(choice) == (KMA, 1)


def test_fit_says_whether_busy_times_changed_the_choice():
    assert choose(pick=JumuahPick(KMA, 2)).fit == "normal"
    assert choose(pick=JumuahPick(KMA, 2), busy=[(at(12, 30), at(12, 40))]).fit == "normal"
    assert choose(pick=JumuahPick(KMA, 1), busy=[(at(12, 30), at(13, 0))]).fit == "moved"
    assert choose().fit == "normal"
    assert choose(busy=[(at(12, 0), at(13, 30))]).fit == "moved"


def test_a_pick_whose_slot_isnt_on_this_friday_is_treated_like_a_clash():
    only_two = [s for s in SLOTS if s.order != 3]
    choice = choose(pick=JumuahPick(KMA, 3), slots=only_two)
    assert chosen(choice) == (KMA, 1)
    assert choice.reason == "Your pick (3rd Jumuah) isn't on this Friday, so this is the earliest Jumuah that fits."


def test_no_pick_yet_gives_the_earliest_that_fits():
    choice = choose()
    assert chosen(choice) == (KMA, 1)
    assert choice.reason == "The earliest Jumuah that fits your calendar."
    choice = choose(busy=[(at(12, 0), at(13, 30))])
    assert chosen(choice) == (KMA, 2)


def test_no_pick_and_everything_clashing_gives_the_earliest():
    choice = choose(busy=[(at(11, 0), at(16, 0))])
    assert chosen(choice) == (KMA, 1)
    assert choice.reason == "Every Jumuah clashes with your calendar, so this is the 1st Jumuah."


def test_a_pick_for_a_masjid_no_longer_listed_doesnt_count():
    gone = uuid.uuid4()
    assert choose(pick=JumuahPick(gone, 1)).reason == "The earliest Jumuah that fits your calendar."


def test_no_slots():
    choice = choose(slots=[])
    assert choice.window is None


def test_the_window_counts_the_drive_how_early_and_the_jumuah_length():
    kma_first = [SLOTS[0]]
    window = slot_windows(kma_first, DRIVES, 5, LENGTHS, [])[0]
    # 12:45 Jumuah, 5 minutes early, 10 minute drive: leave 12:30. 40 minutes long: ends 1:25.
    assert (window.starts_at, window.ends_at) == (at(12, 30), at(13, 25))
    # Busy until exactly 12:30, or from exactly 1:25: it still fits.
    assert slot_windows(kma_first, DRIVES, 5, LENGTHS, [(at(12, 0), at(12, 30))])[0].fits
    assert slot_windows(kma_first, DRIVES, 5, LENGTHS, [(at(13, 25), at(14, 0))])[0].fits
    # One minute into the drive, or one minute before the end: it clashes.
    assert not slot_windows(kma_first, DRIVES, 5, LENGTHS, [(at(12, 0), at(12, 31))])[0].fits
    assert not slot_windows(kma_first, DRIVES, 5, LENGTHS, [(at(13, 24), at(14, 0))])[0].fits
    # A longer "how early" moves the start back.
    assert slot_windows(kma_first, DRIVES, 20, LENGTHS, [])[0].starts_at == at(12, 15)


def test_an_unknown_drive_time_starts_the_window_at_arrival():
    window = slot_windows([SLOTS[0]], {}, 5, LENGTHS, [])[0]
    assert window.trip.leave_at is None
    assert window.starts_at == at(12, 40)


def test_ties_go_to_the_masjid_listed_first():
    same_time = [JumuahSlot(STITTSVILLE, 1, at(13, 0)), JumuahSlot(KMA, 1, at(13, 0))]
    assert chosen(choose(slots=same_time)) == (KMA, 1)
    assert chosen(choose(slots=same_time, listed=[STITTSVILLE, KMA])) == (STITTSVILLE, 1)


def test_ordinals():
    assert [ordinal(n) for n in (1, 2, 3)] == ["1st", "2nd", "3rd"]
