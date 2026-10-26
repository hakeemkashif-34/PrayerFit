"""The background worker. Docker Compose runs it as its own service.

Every minute it runs, in order:
1. Nightly jobs that are due (3:00 am in each user's time zone).
2. MAWAQIT fetches that are due (each linked masjid, once every 6 hours).
3. Busy time checks that are due (each user, once every 15 minutes).
4. Queued calendar updates, like the ones a masjid time change adds.
Each step has its own try, so one failing doesn't stop the others.

    python -m app.worker                 checks every minute for due jobs (the service)
    python -m app.worker run-now         runs today's job for every user right away
    python -m app.worker run-now --email you@gmail.com --force
"""

import argparse
import logging
import time
from datetime import UTC, datetime

from app.busy_checks import run_due_checks
from app.db import get_engine
from app.http_client import new_http_client
from app.masjid_times.scheduler import run_due_fetches
from app.nightly import run_due_jobs, run_now
from app.update_jobs import run_due_updates

logger = logging.getLogger("app.worker")

CHECK_EVERY_SECONDS = 60


STEPS = (
    ("nightly jobs", run_due_jobs),
    ("masjid times", run_due_fetches),
    ("busy checks", run_due_checks),
    ("calendar updates", run_due_updates),
)


def run_once() -> None:
    with new_http_client() as http:
        for name, step in STEPS:
            try:
                step(get_engine(), http, datetime.now(UTC))
            except Exception:  # noqa: BLE001 - for example, Postgres restarting. Try again next minute.
                logger.exception("Checking for %s failed", name)


def loop() -> None:
    logger.info("Worker started. Checking for due jobs every %d seconds.", CHECK_EVERY_SECONDS)
    while True:
        run_once()
        time.sleep(CHECK_EVERY_SECONDS)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="python -m app.worker")
    commands = parser.add_subparsers(dest="command")
    now_parser = commands.add_parser("run-now", help="run today's nightly job right away")
    now_parser.add_argument("--email", help="only this user (the email they signed in with)")
    now_parser.add_argument("--force", action="store_true", help="run again even if it already ran today")
    args = parser.parse_args(argv)

    if args.command != "run-now":
        loop()
        return
    with new_http_client() as http:
        results = run_now(get_engine(), http, datetime.now(UTC), email=args.email, force=args.force)
    if not results:
        print("No users with setup finished" + (f" and email {args.email}." if args.email else "."))
    for result in results:
        line = f"{result.job_id}: {result.status}, {result.events_sent} events sent to Google"
        print(line + (f". {result.message}" if result.message else ""))


if __name__ == "__main__":
    main()
