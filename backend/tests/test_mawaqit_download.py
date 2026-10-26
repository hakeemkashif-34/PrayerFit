"""Reading a MAWAQIT page from a saved ID: a page name, or "id/9793" for a share link.

MAWAQIT answers a share link (mawaqit.net/en/id/9793) with the page itself,
with no redirect. Redirects are still followed by hand, a few hops, and
only within mawaqit.net.
"""

import pytest

from app.masjid_times.mawaqit import (
    MAX_REDIRECTS,
    BadLink,
    download,
    external_id_from_link,
    page_url,
)
from app.masjid_times.source import SourceFailed


@pytest.mark.parametrize(
    "link, saved",
    [
        ("https://mawaqit.net/en/id/9793", "id/9793"),
        ("https://mawaqit.net/id/9793", "id/9793"),
        ("https://www.mawaqit.net/fr/id/11810?utm=share", "id/11810"),
        ("https://mawaqit.net/en/cio-gatineau", "cio-gatineau"),
        # "id" is Indonesian too, so this is a page link.
        ("https://mawaqit.net/id/cio-gatineau", "cio-gatineau"),
        ("https://mawaqit.net/en/w/kma-masjid-ottawa", "kma-masjid-ottawa"),
    ],
)
def test_links_give_a_saved_id(link, saved):
    assert external_id_from_link(link) == saved


@pytest.mark.parametrize(
    "link",
    [
        "http://mawaqit.net/en/id/9793",
        "https://mawaqit.net.evil.com/en/id/9793",
        "https://mawaqit.net/en/id/abc",
        "https://mawaqit.net/en/id/9793/extra",
        "https://mawaqit.net/en/id",
        "https://mawaqit.net/",
    ],
)
def test_bad_links_are_refused(link):
    with pytest.raises(BadLink):
        external_id_from_link(link)


def test_urls_are_built_from_the_saved_id():
    assert page_url("id/9793") == "https://mawaqit.net/en/id/9793"
    assert page_url("cio-gatineau") == "https://mawaqit.net/en/cio-gatineau"
    for bad in ("id/abc", "id/9793/x", "../etc", "ID/9793"):
        with pytest.raises(BadLink):
            page_url(bad)


def test_a_share_link_is_read_directly(http, fake_mawaqit):
    fake_mawaqit.pages["id/9793"] = "<html>KMA</html>"
    assert download(http, "id/9793") == "<html>KMA</html>"
    assert [r.url.path for r in fake_mawaqit.requests] == ["/en/id/9793"]


def test_a_redirect_within_mawaqit_is_followed(http, fake_mawaqit):
    fake_mawaqit.redirects["/en/id/9793"] = "/en/kma-masjid-ottawa"
    fake_mawaqit.pages["kma-masjid-ottawa"] = "<html>KMA</html>"
    assert download(http, "id/9793") == "<html>KMA</html>"
    assert [str(r.url) for r in fake_mawaqit.requests] == [
        "https://mawaqit.net/en/id/9793", "https://mawaqit.net/en/kma-masjid-ottawa",
    ]


@pytest.mark.parametrize(
    "location", ["https://evil.example/en/kma", "http://mawaqit.net/en/kma", "https://mawaqit.net:8443/en/kma", "https://a@mawaqit.net/en/kma"]
)
def test_a_redirect_anywhere_else_is_refused(http, fake_mawaqit, location):
    fake_mawaqit.redirects["/en/id/9793"] = location
    with pytest.raises(SourceFailed, match="another site"):
        download(http, "id/9793")
    assert len(fake_mawaqit.requests) == 1


def test_too_many_redirects_are_refused(http, fake_mawaqit):
    fake_mawaqit.redirects["/en/id/9793"] = "/en/id/9793"
    with pytest.raises(SourceFailed, match="more than 3 times"):
        download(http, "id/9793")
    assert len(fake_mawaqit.requests) == MAX_REDIRECTS + 1
