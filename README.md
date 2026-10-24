# Muslim Calendar

A website that keeps your prayer times up to date in your Google Calendar.

See [Muslim_Calendar_App.md](Muslim_Calendar_App.md) for the full product description and [LEARNING.md](LEARNING.md) for how each part works.

## Stack

1. Backend: Python and FastAPI
2. Database: Postgres
3. Runs with Docker Compose
4. Tests: pytest, run by GitHub Actions on every push and pull request

## Run it with Docker

```bash
cp .env.example .env        # then edit the values
docker compose up --build
```

Open http://localhost:8000/health. You should see `{"status":"ok","database":"ok"}`.

To see the error case, stop the database with `docker compose stop db` and refresh. You should get a 503 error and `{"status":"error","database":"unreachable"}`. Start it again with `docker compose start db`.

## Prayer times

Open http://localhost:8000/prayer-times?latitude=45.4215&longitude=-75.6972&date=2026-10-24 to get Ottawa's prayer times for that day.

| Parameter | Required | Default | Example |
|---|---|---|---|
| `latitude` | yes | | `45.4215` |
| `longitude` | yes | | `-75.6972` |
| `date` | no | today in that time zone | `2026-10-24` |
| `method` | no | `isna` | `isna`, `mwl`, `egyptian`, `karachi`, `umm_al_qura` |
| `asr_method` | no | `standard` | `standard`, `hanafi` |
| `timezone` | no | `DEFAULT_TIMEZONE` from `.env`, or `America/Toronto` | `America/Edmonton` |

Every time comes back with where it came from (`"source": "calculated"`, the method, and the Asr method). http://localhost:8000/docs lists every endpoint and lets you try them in the browser.

## Run the tests

The tests need a real Postgres. The easiest way is to start only the database from Docker Compose.

```bash
cp .env.example .env            # skip if you already have one
docker compose up -d db         # start Postgres in the background

cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# Inside Docker the database is called "db", but from your laptop it's "localhost".
export DATABASE_URL=postgresql://muslim_calendar:change-me@localhost:5432/muslim_calendar
pytest
```

Use the same user, password, and database name as in your `.env`. You should see `235 passed`.

The prayer time tests don't need the database. To run only those: `pytest -k "not health"`.

When you're done, stop Postgres with `docker compose down`.
