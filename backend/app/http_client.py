"""The HTTP client used for every call to Google and Photon.

It comes in through a FastAPI dependency, so tests can swap in fakes and
no test ever reaches the real Google or Photon.
"""

import logging
import time
from collections.abc import Iterator

import httpx2

# Seconds to wait before giving up, for Google and Photon. A timeout is
# treated like any other temporary error: stop, and finish on the next run.
HTTP_TIMEOUT = 10

logger = logging.getLogger("app.outside_services")

# httpx2 logs every URL at INFO. A Photon URL has what the user typed in
# it, so these loggers only report warnings and errors.
for name in ("httpx2", "httpcore2"):
    logging.getLogger(name).setLevel(logging.WARNING)


def new_http_client() -> httpx2.Client:
    return httpx2.Client(timeout=HTTP_TIMEOUT)


def get_http() -> Iterator[httpx2.Client]:
    with new_http_client() as client:
        yield client


def transport_reason(error: httpx2.TransportError) -> str:
    """"timeout" or "connection error". Never the error's own text, which can hold the URL."""
    return "timeout" if isinstance(error, httpx2.TimeoutException) else "connection error"


def log_failure(service: str, reason: str, started: float) -> None:
    """Log why an outside service failed and how long it took.

    Only the service name, the reason (like "status 504" or "timeout"), and
    the time go in the log. Never the URL, the address, or the location.
    """
    logger.warning("%s failed: %s after %.1f s", service, reason, time.monotonic() - started)
