"""The worker runs nightly jobs, MAWAQIT fetches, and queued updates, and one failing doesn't stop the rest."""

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
            ("calendar updates", lambda engine, http, now: ran.append("updates")),
        ),
    )
    worker.run_once()
    assert ran == ["nightly", "fetches", "updates"]


def test_the_steps_run_in_order():
    assert [name for name, _ in worker.STEPS] == ["nightly jobs", "masjid times", "calendar updates"]
