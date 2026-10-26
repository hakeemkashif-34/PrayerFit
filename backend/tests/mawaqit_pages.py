"""Made-up MAWAQIT pages for tests, built the way a real page holds its data.

KMA's real page (fixtures/mawaqit/kma_page.html, in test_mawaqit_kma.py)
is the main parser test.
These let a test change one value, like an impossible time, without
editing the saved page.
"""

import copy
import json

DEFAULT_DAY = ["05:30", "07:00", "12:30", "15:30", "18:00", "19:30"]
# Fajr, Dhuhr, Asr, Maghrib, Isha
DEFAULT_IQAMAH = ["+20", "13:00", "+10", "+5", "20:15"]
DAYS_IN_MONTH = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def conf(jumua: str | None = "13:30", jumua2: str | None = "14:30", **extra) -> dict:
    """A whole year of the same times. Tests change the parts they need."""
    calendar = [{str(d): list(DEFAULT_DAY) for d in range(1, n + 1)} for n in DAYS_IN_MONTH]
    iqamah = [{str(d): list(DEFAULT_IQAMAH) for d in range(1, n + 1)} for n in DAYS_IN_MONTH]
    return {
        "name": "Test Masjid",
        "calendar": calendar,
        "iqamaCalendar": iqamah,
        "iqamaEnabled": True,
        "jumua": jumua,
        "jumua2": jumua2,
        "jumua3": None,
        **extra,
    }


def page(data: dict) -> str:
    """The data inside a page, with a script that must never be run."""
    return (
        "<!DOCTYPE html><html><head><title>Test Masjid - Mawaqit</title>"
        "<script>window.location = 'https://example.com/never-run';</script></head><body>"
        "<div id='times'></div>"
        f"<script>\n    var confData = {json.dumps(data)};\n    var other = 1;\n</script>"
        "</body></html>"
    )


def set_day(data: dict, month: int, day: int, times: list[str] | None = None, iqamah: list | None = None) -> dict:
    data = copy.deepcopy(data)
    if times is not None:
        data["calendar"][month - 1][str(day)] = times
    if iqamah is not None:
        data["iqamaCalendar"][month - 1][str(day)] = iqamah
    return data
