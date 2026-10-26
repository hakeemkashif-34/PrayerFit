"""The worker runs nightly jobs, MAWAQIT fetches, busy checks, queued updates, and usage stats, and one failing doesn't stop the rest."""

from app import worker


def test_one_failing_step_doesnt_stop_the_others(monkeypatch):
    ran = []

    def broken(engine, http, now):
        ran.append("nightly")
        raise RuntimeError("Postgres restarting")

    monkeypatch.setattr(worker, "get_engine", lambda: None)
    monkeypatch.setattr(
        worker,
        "STEPS",
        (
            ("nightly jobs", broken),
            ("masjid times", lambda engine, http, now: ran.append("fetches")),
            ("busy checks", lambda engine, http, now: ran.append("busy")),
            ("calendar updates", lambda engine, http, now: ran.append("updates")),
            ("usage stats", lambda engine, http, now: ran.append("stats")),
        ),
    )
    worker.run_once()
    assert ran == ["nightly", "fetches", "busy", "updates", "stats"]


def test_the_steps_run_in_order():
    assert [name for name, _ in worker.STEPS] == ["nightly jobs", "masjid times", "busy checks", "calendar updates", "usage stats"]
