"""link-mawaqit only accepts mawaqit.net masjid pages, and keeps only the page name."""

import pytest

from app.masjid_times.mawaqit import BadLink, page_url, slug_from_link


@pytest.mark.parametrize(
    "link",
    [
        "https://mawaqit.net/en/kma-kanata",
        "https://www.mawaqit.net/en/kma-kanata",
        "https://mawaqit.net/fr/kma-kanata",
        "https://mawaqit.net/en/m/kma-kanata",
        "https://mawaqit.net/en/w/kma-kanata?showOnly5PrayerTimes=0",
        "https://mawaqit.net/kma-kanata",
        "  https://MAWAQIT.net/en/KMA-Kanata/  ",
    ],
)
def test_accepts_mawaqit_pages(link):
    assert slug_from_link(link) == "kma-kanata"


@pytest.mark.parametrize(
    "link",
    [
        "http://mawaqit.net/en/kma-kanata",  # not https
        "https://mawaqit.net.evil.com/en/kma-kanata",
        "https://evil.com/mawaqit.net/en/kma-kanata",
        "https://api.mawaqit.net/en/kma-kanata",  # only the main site
        "https://mawaqit.net:8443/en/kma-kanata",
        "https://user:pass@mawaqit.net/en/kma-kanata",
        "https://mawaqit.net/",
        "https://mawaqit.net/en/",
        "https://mawaqit.net/en/kma-kanata/extra",
        "https://mawaqit.net/en/../../etc",
        "https://mawaqit.net/en/kma_kanata",
        "https://mawaqit.net/en/kma%2Fkanata",
        "mawaqit.net/en/kma-kanata",
        "javascript:alert(1)",
        "",
    ],
)
def test_rejects_anything_else(link):
    with pytest.raises(BadLink):
        slug_from_link(link)


def test_the_app_builds_the_page_url_itself():
    assert page_url("kma-kanata") == "https://mawaqit.net/en/kma-kanata"
    with pytest.raises(BadLink):
        page_url("../admin")
