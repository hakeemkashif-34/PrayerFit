"""The HTTP client used for every call to Google.

It comes in through a FastAPI dependency, so tests can swap in a fake
Google and no test ever reaches the real one.
"""

from collections.abc import Iterator

import httpx2

# Seconds to wait for Google before giving up. A timeout is treated like
# any other temporary error: stop, and finish on the next run.
GOOGLE_TIMEOUT = 10


def get_google_http() -> Iterator[httpx2.Client]:
    with httpx2.Client(timeout=GOOGLE_TIMEOUT) as client:
        yield client
