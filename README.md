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

Open http://localhost:8000/health. You should see `{"status":"ok"}`.

## Run the tests without Docker

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```
