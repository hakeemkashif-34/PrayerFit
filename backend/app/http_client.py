"""The HTTP client used for every call to Google and OpenStreetMap.

It comes in through a FastAPI dependency, so tests can swap in fakes and
no test ever reaches the real Google, Nominatim, or Overpass.
"""

import logging
from collections.abc import Iterator

import httpx2

# Seconds to wait before giving up. A timeout is treated like any other
# temporary error: stop, and finish on the next run.
HTTP_TIMEOUT = 10

# httpx2 logs every URL at INFO. A Nominatim URL has the user's address in
# it, so these loggers only report warnings and errors.
for name in ("httpx2", "httpcore2"):
    logging.getLogger(name).setLevel(logging.WARNING)


def new_http_client() -> httpx2.Client:
    return httpx2.Client(timeout=HTTP_TIMEOUT)


def get_http() -> Iterator[httpx2.Client]:
    with new_http_client() as client:
        yield client
