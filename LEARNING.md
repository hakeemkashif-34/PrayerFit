# Learning Notes

What each part of the app does and why it was built that way. Updated after each milestone.

---

## Milestone 1: Setup

### 1. Repo basics

1. **`.gitignore`**
   a) Tells git which files never to commit.
   b) Most important line: `.env`, so real passwords and keys stay on your machine.
   c) Also skips generated junk like `__pycache__/`, `.venv/`, and `node_modules/`.

2. **`.env.example`**
   a) A template listing every setting the app needs, with fake values.
   b) You copy it to `.env` and fill in real values.
   c) Why: new developers (and CI, and Azure later) can see what's needed without anyone sharing secrets.

3. **`README.md`**
   a) How to run the app and the tests. The first thing a recruiter or teammate reads.

### 2. Backend (`backend/`)

1. **`app/main.py`**
   a) Creates the FastAPI app and the `/health` endpoint.
   b) `@app.get("/health")` means "when a GET request comes to /health, run this function".
   c) Why a health check: Docker, CI, and Azure need a cheap way to ask "is the app working?"
   d) It runs `SELECT 1`, the smallest possible query, to prove Postgres answers.
   e) Database up: status 200 and `{"status": "ok", "database": "ok"}`.
   f) Database down: status 503 and `{"status": "error", "database": "unreachable"}`.
   g) Why 503 (Service Unavailable): the server itself is running, but it can't do its job. Azure and other tools treat any 5xx as "unhealthy", so they can restart the app or stop sending it traffic. Returning 200 with "error" in the body would look healthy to them.
   h) `Depends(get_engine)` is FastAPI's dependency injection. FastAPI calls `get_engine()` and passes the result in. Because the engine isn't hard-coded, tests can swap in a different one.
   i) Only `SQLAlchemyError` is caught, so a database problem gives a 503, but a typo in our own code still shows up as a normal error instead of being hidden.

2. **`app/db.py`**
   a) Sets up the connection to Postgres.
   b) The **engine** is SQLAlchemy's connection manager. It keeps a pool of open connections so each request doesn't open a new one.
   c) `database_url()` reads `DATABASE_URL` from the environment and fails with a clear message if it's missing.
   d) It changes `postgresql://` to `postgresql+psycopg://`. Without that, SQLAlchemy looks for the older `psycopg2` driver, which isn't installed.
   e) `@lru_cache` on `get_engine()` means the engine is made once, on the first request, then reused.
   f) It's made on first use, not when the app starts, so the app can still start and report a 503 when the database is down.
   g) `pool_pre_ping=True` checks a pooled connection still works before using it. Without it, the first request after a Postgres restart would fail on a dead connection.
   h) `connect_timeout: 3` gives up after 3 seconds, so `/health` answers quickly instead of hanging when the database can't be reached.

3. **`app/__init__.py`**
   a) Empty file that makes `app` a Python package, so `from app.main import app` works.

4. **`requirements.txt`**
   a) Packages the app needs to run: `fastapi` (the framework), `uvicorn` (the web server that runs it), `sqlalchemy` (talks to the database), and `psycopg` (the Postgres driver SQLAlchemy uses).
   b) `psycopg[binary]` comes with its own compiled copy of the Postgres client library, so nothing extra needs installing on your laptop or in Docker.
   c) Versions are pinned (`==`) so your laptop, CI, and Docker all install the same thing.

5. **`requirements-dev.txt`**
   a) Starts with `-r requirements.txt`, then adds testing tools.
   b) Kept separate so the Docker image doesn't ship test tools it never uses.
   c) `httpx2` is what FastAPI's `TestClient` uses to send fake requests. The older `httpx` still works but prints a deprecation warning.

### 3. Tests

1. **`tests/test_health.py`**
   a) `test_health_ok_when_database_is_up`: calls `/health` against a real Postgres and expects 200.
   b) `test_health_503_when_database_is_down`: expects 503 and the "unreachable" message.
   c) `TestClient` runs the app in memory, so no web server is needed. A real Postgres is needed, found through `DATABASE_URL`.
   d) Why a real database instead of a fake one: a fake only proves the code calls the fake correctly. A real one proves the app can actually connect, with the real driver and real connection settings.
   e) The "down" test uses a **fixture**, `database_down`. pytest runs the code before `yield` before the test and the code after `yield` after it, even if the test fails.
   f) The fixture uses `app.dependency_overrides` to make FastAPI use an engine pointing at port 1 on this machine, where nothing is listening. The connection is refused straight away, like a database that's down.
   g) After the test, the fixture clears the override so later tests use the real database again.
   h) The real database is never stopped, so the tests stay fast and don't affect each other.
   i) pytest finds any function starting with `test_` in a file starting with `test_`.

2. **`pytest.ini`**
   a) `testpaths = tests`: where to look for tests.
   b) `pythonpath = .`: lets tests import `app` from the `backend` folder.

### 4. Docker

1. **`backend/Dockerfile`**
   a) A recipe for building an image: a small Linux system with Python and the app inside.
   b) `requirements.txt` is copied and installed before the code. Docker caches each step, so changing code doesn't reinstall every package.
   c) Runs as a normal user, not root, so a bug in the app can't take over the container.
   d) `--host 0.0.0.0` makes the server reachable from outside the container. The default (`127.0.0.1`) only listens inside it.

2. **`backend/.dockerignore`**
   a) Keeps `.venv`, caches, and tests out of the image so it stays small.

3. **`docker-compose.yml`**
   a) Runs two containers together: `db` (Postgres 17) and `backend`.
   b) `${POSTGRES_USER}` and the others are read from `.env`.
   c) Inside Compose, containers reach each other by service name. That's why `DATABASE_URL` uses `@db:5432`, not `localhost`.
   d) From your laptop (for example when running the tests), the database is at `localhost:5432` instead, because Compose publishes port 5432.
   e) `volumes: db-data` keeps the database's data when containers are removed. `docker compose down -v` deletes it.
   f) The `healthcheck` runs `pg_isready`. With `condition: service_healthy`, the backend waits until Postgres accepts connections, not just until its container starts.
   g) `$${POSTGRES_USER}` has two `$` so Compose passes `$POSTGRES_USER` to the container's shell instead of filling it in itself.

### 5. GitHub Actions

1. **`.github/workflows/tests.yml`**
   a) On every push and pull request, GitHub starts a fresh Ubuntu machine, installs Python 3.13 and the packages, and runs `pytest`.
   b) `services: postgres` starts a real Postgres 17 container next to the tests, the same version as Docker Compose.
   c) The health options make GitHub wait until Postgres accepts connections before running the tests, the same idea as the Compose healthcheck.
   d) `DATABASE_URL` is set for the whole job so the tests can find it. The username and password are throwaway test values, not secrets. That database only exists while the job runs.
   e) A red X on a commit or PR means a test failed.
   f) `cache: pip` saves downloaded packages between runs, so later runs are faster.
   g) Python 3.13 matches the Dockerfile, so tests run on the same version as the real app.

### 6. How to check it works

1. **Tests on your laptop**
   a) Start only the database: `docker compose up -d db`.
   b) In `backend`, activate the virtual environment and install `requirements-dev.txt`.
   c) Point the tests at the database: `export DATABASE_URL=postgresql://muslim_calendar:change-me@localhost:5432/muslim_calendar` (use your `.env` values).
   d) Run `pytest`. You should see `2 passed`.

2. **The whole app in Docker**
   a) Run `docker compose up --build` and open http://localhost:8000/health. You should see `"database":"ok"`.
   b) In another terminal, run `docker compose stop db` and refresh. You should get a 503 and `"database":"unreachable"`.
   c) Run `docker compose start db` and refresh. It goes back to ok.

3. **GitHub Actions**
   a) Open the PR and look for the green check next to "Tests". The Actions tab shows the full log.

---

## Milestone 2: Prayer times

### 1. Where things are

1. **`backend/app/prayer_times/`**: the calculation. Pure maths, no database and no web code, so it's easy to test.
   a) `astronomy.py`: where the sun is, and when it reaches a given height in the sky.
   b) `methods.py`: the calculation methods (ISNA and others) and the Asr methods.
   c) `calculator.py`: puts it together into Fajr, Sunrise, Dhuhr, Asr, Maghrib, and Isha for one place and one day.
   d) `__init__.py`: lists what other files can import, so they write `from app.prayer_times import calculate_prayer_times`.
2. **`backend/app/routers/prayer_times.py`**: the `GET /prayer-times` endpoint.
   a) A router is a group of endpoints in its own file. `main.py` adds it with `app.include_router(...)`. This keeps `main.py` small as more endpoints come.

### 2. How prayer times are worked out

Every prayer time is "the moment the sun is at a certain height". The height is called the **altitude**, in degrees. 0 is the horizon, negative is below it.

| Prayer | When it starts |
|---|---|
| Fajr | Sun is 15 to 19.5 degrees below the horizon, before sunrise (depends on the method) |
| Sunrise | Top of the sun at the horizon. Ends Fajr. |
| Dhuhr | Just after the sun is highest (solar noon) |
| Asr | A stick's shadow equals its noon shadow plus 1 stick length (Hanafi: 2) |
| Maghrib | Sunset |
| Isha | Sun is 15 to 18 degrees below the horizon, after sunset (Umm al-Qura: 90 minutes after Maghrib) |

So the job is: (1) know where the sun is at any moment, and (2) find the moment it reaches each altitude.

### 3. `astronomy.py`

1. **Where the formulas come from**
   a) Jean Meeus, "Astronomical Algorithms". It's the standard book for this. The adhan library uses it too, which is why our times can be compared with it.
   b) Each function names the chapter it comes from.

2. **`julian_day`**
   a) Counts days from a fixed start point instead of using year, month, day.
   b) Why: the gap between two dates becomes a subtraction. No months or leap years to handle.

3. **`sun_position`**
   a) Gives three numbers for midnight UTC on a date.
   b) **Declination**: how far north or south of the equator the sun is. About +23.4 in June, -23.4 in December. This is why summer days are long.
   c) **Right ascension**: the sun's position along the sky, like a longitude for the sky.
   d) **Sidereal time**: how far the Earth has turned, measured against the stars.

4. **`SolarDay`**
   a) Works out the sun for yesterday, today, and tomorrow, then estimates any moment in between (interpolation, chapter 3). The sun moves smoothly, so three points are enough.
   b) **Hour angle**: how far the sun is past this place's meridian (the north-south line overhead). 0 at solar noon.
   c) `noon()`: solar noon, when the hour angle is 0.
   d) `time_at_altitude(target, after_noon)`: when the sun is at the target altitude. Returns `None` if it never gets there that day.

5. **Why `time_at_altitude` uses binary search**
   a) From solar noon to solar midnight, the sun only goes down. So the answer is somewhere in that half day.
   b) Check the middle. If the sun is still above the target, the answer is in the later half. Otherwise the earlier half. Repeat.
   c) Each step halves the gap. About 23 steps get from half a day to 0.01 seconds.
   d) If the sun is still above the target at midnight (or below it at noon), there's no answer. That's how we know it never gets dark enough.
   e) Why not the book's method: the book guesses a time and corrects it once. That's fast and usually within seconds. But on days when the sun only just reaches the target (Fajr at 18 degrees in London or Edmonton), I measured it up to 4 minutes off. Repeating the correction fixed that, but at Alert it jumped to the wrong day. Binary search can't do either. I checked it against a minute-by-minute scan and it matched to 0.003 seconds.

6. **Sunrise altitude is -0.833, not 0**
   a) The air bends light, so you see the sun about 0.57 degrees before it's really over the horizon.
   b) Sunrise is when the top of the sun shows, not the centre. That's another 0.27 degrees (half the sun's width).

### 4. `methods.py`

1. **Calculation methods**: different groups of scholars disagree on how dark it has to be for Fajr and Isha.

| Method | Fajr angle | Isha |
|---|---|---|
| `isna` (default) | 15 | 15 |
| `mwl` | 18 | 17 |
| `egyptian` | 19.5 | 17.5 |
| `karachi` | 18 | 18 |
| `umm_al_qura` | 18.5 | 90 minutes after Maghrib |

2. ISNA is the default because most masjids in Ottawa use it.
3. Umm al-Qura uses 120 minutes in Ramadan. That isn't handled yet. It's noted in the code.
4. **Dhuhr is 1 minute after solar noon** for every method except Umm al-Qura.
   a) Solar noon is when the centre of the sun crosses the meridian. The sun is about 2 minutes wide, so its back edge crosses about 1 minute later.
   b) These values match the adhan library.
5. **Asr methods**: `standard` (Shafi'i, Maliki, Hanbali) uses 1 shadow length. `hanafi` uses 2, so Hanafi Asr is always later.
6. `StrEnum` makes each choice a string, like `"isna"`. FastAPI uses that to check the URL and to show the choices on `/docs`.

### 5. `calculator.py`

1. **`calculate_prayer_times(latitude, longitude, on_date, time_zone, method, asr_method)`**
   a) `on_date` is a local date, like a date on a wall calendar.
   b) `time_zone` defaults to `America/Toronto`.
   c) Returns a `DailyPrayerTimes` with six `PrayerTime`s.

2. **All the maths is in UTC**
   a) UTC has no daylight saving, so adding hours is always safe.
   b) Only at the end is each time converted to the local zone with `.astimezone(zone)`.
   c) Next day means the next calendar date (`date + timedelta(days=1)` on a `date`), never "add 24 hours". On a daylight saving day, a local day is 23 or 25 hours long.

3. **`_utc_day_for`**: picks the UTC date whose solar noon falls on the local date.
   a) Almost always it's the same date.
   b) Near the date line (Samoa, for example) it's the day before or after. Without this, you'd get the wrong day's times.

4. **Asr uses the sun's declination at solar noon**
   a) The rule compares with the noon shadow, so the noon shadow should use where the sun is at noon.
   b) adhan uses where the sun is at midnight UTC instead, which is 5 or 6 pm the day before in Edmonton. That moves Asr by up to 2 minutes there.

5. **Rounding**
   a) `round_up_to_minute` for Fajr, Dhuhr, Asr, Maghrib, and Isha. 12:00:01 shows as 12:01. The app never shows a prayer before it starts.
   b) `round_down_to_minute` for sunrise. Sunrise ends Fajr, so showing it a little early is the safe side.
   c) Rounding happens in UTC. Every time zone in use today is a whole number of minutes from UTC, so this gives the same answer as rounding the local time.

6. **High latitude rules**
   a) In Edmonton in June the sun only goes about 13 degrees below the horizon. It never reaches the 15 that ISNA uses, so there's no normal Fajr or Isha.
   b) Instead of an error, the app uses a share of the night (sunset to sunrise).
   c) Below 48 degrees: Fajr no earlier than the middle of the night, Isha no later. Same cut-off as adhan's recommended rule.
   d) From 48 degrees: Fajr no earlier than the last seventh of the night, Isha no later than the first seventh. Summer nights up there are short, so half the night would be too loose.
   e) The limit is used whenever the normal time is missing or goes past it.
   f) Fajr uses the night it ends (last sunset to this sunrise). Isha uses the night it starts (this sunset to tomorrow's sunrise). Because both use the same night, Isha can never run past the next Fajr. adhan uses tonight for Fajr too, which moves it by up to about 40 seconds in late summer.
   g) Above 65 degrees (Inuvik, Alert, Antarctica), some days have no sunset (midnight sun) or no sunrise (polar night). The app uses the times at 65 degrees, the nearest latitude where the sun rises and sets every day.
   h) It does that every day, not just on days with no sunrise or sunset. The days next to those have only minutes of daylight or darkness. Asr lands on Dhuhr, and switching rules made times jump by over an hour from one day to the next.

7. **Where each time came from**
   a) Every `PrayerTime` has `source = "calculated"`, the `method`, the `asr_method`, and `high_latitude_rule` (`None` unless a rule replaced the time).
   b) Later, masjid times will have their own source, so users can tell calculated times and iqamah times apart.
   c) `exact_time` keeps the time before rounding, in UTC. The tests use it. The endpoint doesn't show it.

### 6. `GET /prayer-times`

1. Takes `latitude`, `longitude`, `date`, `method`, `asr_method`, and `timezone`. Only latitude and longitude are required.
2. Example: `/prayer-times?latitude=45.4215&longitude=-75.6972&date=2026-10-24`

```json
{
  "date": "2026-10-24",
  "timezone": "America/Toronto",
  "latitude": 45.4215,
  "longitude": -75.6972,
  "method": "isna",
  "asr_method": "standard",
  "times": {
    "fajr": {"time": "2026-10-24T06:10:00-04:00", "source": "calculated", "method": "isna", "asr_method": "standard", "high_latitude_rule": null},
    "sunrise": {"time": "2026-10-24T07:31:00-04:00", "...": "..."},
    "dhuhr": {"time": "2026-10-24T12:48:00-04:00", "...": "..."},
    "asr": {"time": "2026-10-24T15:35:00-04:00", "...": "..."},
    "maghrib": {"time": "2026-10-24T18:03:00-04:00", "...": "..."},
    "isha": {"time": "2026-10-24T19:24:00-04:00", "...": "..."}
  }
}
```

3. Times include the offset (`-04:00`), so anyone reading them knows exactly which moment it is.
4. No date means today in that time zone, not the server's. The server on Azure will most likely run on UTC.
5. The default time zone comes from `DEFAULT_TIMEZONE` in `.env`, then `America/Toronto`.
6. Bad input gives 422 (Unprocessable Content). FastAPI checks the numbers, date, and method names by itself from the type hints. The time zone is checked by hand, since any string could be sent.
7. `../../etc/passwd` as a time zone also gives 422. `ZoneInfo` refuses names that try to leave the time zone folder, and the endpoint turns that error into a 422.
8. The Python name is `on_date` with `alias="date"`, so the URL still says `date` but the code doesn't hide Python's `date` type.
9. `tzdata` in `requirements.txt` gives Python the time zone rules on computers that don't have them, like Windows.

### 7. Tests

1. **`tests/places.py`**: the places and years every test shares. 7 cities to compare with other libraries, plus St. John's (a half hour time zone), Iqaluit, Inuvik, Alert, and McMurdo Station for the far north and south.

2. **`test_prayer_times_reference.py`**: compares with two well-known libraries, every day of 2026 and 2028 (a leap year), for Ottawa, Toronto, Edmonton, Mecca, London, Sydney, and Karachi.
   a) adhanpy (the Python version of adhan) for Fajr, Sunrise, Dhuhr, Maghrib, and Isha, for all 5 methods.
   b) praytimes (the Python version of PrayTimes.org) for Asr, standard and Hanafi.
   c) Both are in `requirements-dev.txt` only. The app never uses them.
   d) Every time must match within 1 minute. In practice the worst gap with adhanpy is 10 seconds, and with PrayTimes about 25 seconds for Asr.
   e) Asr is compared with PrayTimes because adhanpy uses the wrong declination for Asr (see section 5, point 4). PrayTimes uses the declination at Asr, which is within 25 seconds of ours.
   f) Fajr is checked against adhanpy's own sunrise and sunset times with our night rule applied, because adhanpy uses a different night for the high latitude rule (section 5, point 6f).
   g) Times are compared before rounding. adhanpy rounds to the nearest minute and we round up, so rounded times can be a minute apart even when the maths agrees. adhanpy also has a bug at :59 (12:59:45 shows as 12:59, not 13:00).
   h) To get adhanpy's times before rounding, a **fixture** uses `monkeypatch` to swap its rounding function for one that does nothing, only during that test.
   i) I broke the code on purpose (a wrong Fajr angle, a wrong Dhuhr offset, the wrong Asr declination) to check the tests fail. They did.

3. **`test_daylight_saving.py`**: Toronto's clock changes on March 8 and November 1, 2026.
   a) Every time in the week around each change is on the right date with the right offset (-05:00 or -04:00).
   b) On the wall clock, every prayer jumps by about an hour. In real time, one Dhuhr to the next is still about 24 hours.
   c) A Python trap: subtracting two times in the same `ZoneInfo` compares wall clocks. The March 7 to March 8 Dhuhr gap comes out as 25 hours. Converting both to UTC first gives the real gap. The tests do that everywhere times are compared.

4. **`test_prayer_times_rules.py`**
   a) Rounding: start times are never before the exact time and less than a minute after it. Sunrise is the other way round.
   b) Every time says `"calculated"` plus its method and Asr method.
   c) Order: Fajr < Sunrise < Dhuhr < Asr < Maghrib < Isha, and Isha is never after the next day's Fajr. Every place, every method, every day of 2026.
   d) Hanafi Asr is always later than standard Asr, every place, every day.
   e) These tests found two real bugs: the jump to the wrong day at Alert, and Asr landing in the same minute as Dhuhr near the poles. Those led to the binary search and to using 65 degrees every day.

5. **`test_high_latitude.py`**
   a) Edmonton in June: proves the sun never reaches 15 degrees, then checks Fajr and Isha are exactly one seventh of the right night.
   b) St. John's in June with the Egyptian method: checks the middle of the night rule.
   c) Ottawa and Mecca: no rule is ever used, every day, every method. The rules must never touch normal times.
   d) Inuvik on June 21 (midnight sun) and December 21 (polar night), and McMurdo Station: times match the ones at 65 degrees.

6. **`test_prayer_times_endpoint.py`**: the endpoint returns all six times in order, matches the calculator, shows sources and the high latitude rule, uses the time zone, and gives 422 for bad input.

### 8. How to check it works

1. **Tests**
   a) Start the database and set `DATABASE_URL` like in milestone 1, then run `pytest` in `backend`. You should see `235 passed`.
   b) Only the prayer time tests (no database needed): `pytest -k "not health"`. You should see `233 passed, 2 deselected`.

2. **In the browser**
   a) Run `docker compose up --build`.
   b) Open http://localhost:8000/prayer-times?latitude=45.4215&longitude=-75.6972&date=2026-10-24. Fajr should be `06:10`, Maghrib `18:03`.
   c) Add `&asr_method=hanafi`. Asr moves later.
   d) Try Edmonton in June: http://localhost:8000/prayer-times?latitude=53.5461&longitude=-113.4938&date=2026-06-21&timezone=America/Edmonton. Fajr and Isha show `"high_latitude_rule": "seventh_of_the_night"`.
   e) Try a bad time zone, like `&timezone=Mars/Olympus_Mons`. You get a 422.
   f) http://localhost:8000/docs shows the endpoint with every choice in a dropdown.

3. **GitHub Actions**: the PR's "Tests" check runs all 235 tests.

---

## Milestone 3: Google Calendar

### 1. Where things are

1. **`backend/app/config.py`**: reads the Google keys and app settings from the environment. Google keys are only read when a Google endpoint runs, so `/health` works without them.
2. **`backend/app/models.py`**: the database tables (users, sessions, Google tokens, Prayers calendars, prayer events).
3. **`backend/alembic/`** and **`alembic.ini`**: migrations, the history of changes to the tables.
4. **`backend/app/auth/`**: sign-in.
   a) `google_oauth.py`: PKCE, the Google sign-in URL, swapping the code for tokens, refreshing, and reading the ID token.
   b) `crypto.py`: encrypts tokens before they're saved.
   c) `tokens.py`: saves tokens and hands out a working access token, refreshing it when needed.
   d) `sessions.py`: the session cookie and the `current_user` dependency.
5. **`backend/app/routers/auth.py`**: `/auth/google/login`, `/auth/google/callback`, `/auth/logout`, `/me`.
6. **`backend/app/google_calendar.py`**: the only code that talks to the Calendar API. 4 calls, nothing else.
7. **`backend/app/prayers_calendar.py`**: finds, reuses, or recreates the "Prayers" calendar.
8. **`backend/app/prayer_sync.py`**: turns prayer times into events, saves them, and sends them to Google without duplicates.
9. **`backend/app/routers/prayers.py`**: `POST /prayers/today` and `GET /prayers/today/events`.
10. **`backend/app/google_errors.py`**: one error type per kind of Google problem.
11. **`backend/app/google_http.py`** and **`backend/app/clock.py`**: the HTTP client and the current time, as dependencies, so tests can swap them.

### 2. Database and migrations

1. **SQLAlchemy models** describe each table as a Python class. `Mapped[str]` means a column that can't be empty. `Mapped[str | None]` means it can be.
2. **Every table has `user_id`** (except `users`). Every query filters on it. That's how one user can never see another's data.
3. **Alembic** keeps a numbered list of changes to the tables. `alembic upgrade head` applies any that haven't run yet, and records which ran in a table called `alembic_version`.
4. I made the first migration with `alembic revision --autogenerate`, which compares the models with the empty database and writes the `create_table` calls. Then I read it and tidied it.
5. `alembic/env.py` reads `DATABASE_URL` through `app/db.py`, so no password is in `alembic.ini`.
6. Docker runs `alembic upgrade head` before starting the server. The tests run the same migrations once, in `conftest.py`.
7. `test_migrations.py` checks the models and the migrations match. If someone changes a model and forgets a migration, it fails.
8. `get_db` in `app/db.py` gives each request its own database session and closes it after.
9. `expire_on_commit=False`: by default SQLAlchemy forgets every loaded value after a commit and reloads it on the next read. The prayers endpoint commits after each Google call and keeps using the rows, so I turned that off.

### 3. Signing in with Google (OAuth)

1. **The flow** (authorization code flow), all on the server:
   a) `/auth/google/login` sends the browser to Google with a random `state` and a PKCE `code_challenge`.
   b) The user picks an account and clicks Allow.
   c) Google sends the browser to `/auth/google/callback?code=...&state=...`.
   d) The server checks the state, then sends the code and the PKCE `code_verifier` to Google's token endpoint, and gets tokens back.
   e) The browser never sees a Google token. It only gets a session cookie.

2. **State** stops login CSRF. Without it, someone could send me a link that finishes *their* sign-in in *my* browser, and my prayers would go into their calendar. The state is random, stored in a cookie tied to my browser, and has to match what comes back.

3. **PKCE** (Proof Key for Code Exchange, said "pixie")
   a) The server makes a random `code_verifier` and sends Google only its SHA-256 hash, the `code_challenge`.
   b) When swapping the code for tokens, the server sends the verifier. Google hashes it and checks it matches.
   c) Why: if someone steals the code from the redirect (a browser extension, a log), they can't use it without the verifier, which never left the server.
   d) `S256` means the challenge is a SHA-256 hash, not the verifier itself.

4. **The `oauth_flow` cookie** holds the state and verifier between the two requests.
   a) Encrypted with the same Fernet key as the tokens, so the browser can't read or change it.
   b) `Max-Age=600` and Fernet's own time check: the sign-in has to finish within 10 minutes.
   c) `Path=/auth/google`, so it's only sent to the sign-in endpoints.
   d) Deleted on every callback answer, success or failure, so each sign-in flow works once.
   e) I used a cookie instead of a table because it's tied to the browser and needs no cleanup.

5. **Scopes**: `openid` and `email` say who I am. `calendar.app.created` lets the app create its own calendars and manage events on them only. It can't read or change any other calendar. No Gmail, no full calendar access.

6. **`access_type=offline`** asks for a refresh token. **`prompt=consent`** shows the consent screen every time, because Google only sends a refresh token when consent is shown.

7. **Unticked calendar box**: Google lets users untick a scope. The callback saves which scopes came back. Without the calendar one, `/me` shows `"calendar_access": false` and `POST /prayers/today` answers 403 "Sign in again and allow calendar access."

8. **The ID token** is a JWT (3 base64 parts joined by dots) that says who signed in.
   a) I read `sub` (Google's permanent user ID) and `email`. Users are matched by `sub`, since emails can change.
   b) I check the issuer is Google, the audience is my client ID, and it hasn't expired.
   c) I skip the signature check. The OpenID Connect spec (section 3.1.3.7) allows that when the token came straight from Google's token endpoint over HTTPS in the server's own request.

### 4. Tokens

1. **Access token**: lasts about 1 hour. Sent with every Calendar API call.
2. **Refresh token**: used to get a new access token. In Testing mode Google expires it after 7 days.
3. **Encryption** (`crypto.py`): Fernet, from the `cryptography` package. AES encryption plus a signature.
   a) A copy of the database without `TOKEN_ENCRYPTION_KEY` from `.env` is useless.
   b) The signature means a changed value fails to decrypt instead of becoming garbage.
   c) Each encryption adds a random IV, so the same token encrypts differently every time.
   d) If the key is lost or changed, nobody's tokens decrypt and everyone has to sign in again.
4. **Refreshing** (`get_access_token` in `tokens.py`):
   a) If the saved access token has more than 60 seconds left, use it. The margin stops it expiring mid-request.
   b) Otherwise refresh with Google and save the new one.
   c) If Google answers `invalid_grant`, the refresh token is dead. The app sets `needs_reauth`, and the API answers 401 with `"Google sign-in expired. Sign in again."` and `login_url`. No crash.
   d) If the Calendar API rejects a token we thought was fine (401), the client refreshes once and tries once more.
   e) Signing in again saves new tokens and clears `needs_reauth`.

### 5. Sessions and cross-site protection

1. **Session cookie**: `secrets.token_urlsafe(32)`, 256 random bits.
2. **Only the hash is saved**: the `sessions` table has the SHA-256 of the cookie. Someone who reads the database can't sign in with it. SHA-256 without a salt is fine here because the value is random and long, unlike a password.
3. **HttpOnly**: JavaScript can't read the cookie, so a script injected into the page can't steal it.
4. **Secure**: only sent over HTTPS. Browsers treat `http://localhost` as secure, so it works locally. The tests turn it off because the test client uses plain http.
5. **SameSite=Lax**: the browser doesn't send the cookie on POSTs from other sites, but does send it when following a normal link (like Google's redirect back). Strict would drop it on that redirect.
6. **Origin check** (middleware in `main.py`): every POST, PUT, PATCH, and DELETE must have `Origin` equal to `APP_ORIGIN`, or it gets 403. Browsers always send `Origin` with a POST, and a page can't fake it. This is a second guard next to SameSite. A missing Origin is refused too.
7. **Sign-out** (`POST /auth/logout`) deletes the session row, so even a copied cookie stops working.
8. **`current_user`** is a dependency every user endpoint uses. It hashes the cookie, finds an unexpired session, and returns the user, or 401.

### 6. The Prayers calendar

1. `ensure_prayers_calendar` in `prayers_calendar.py`:
   a) No saved calendar: create "Prayers" in the request's time zone and save its ID.
   b) Saved one exists in Google: reuse it.
   c) Google says 404 or 410 (the user deleted it): create a new one, save the new ID, and mark the old events as pending so they go to the new one.
2. It locks the user's row (`SELECT ... FOR UPDATE`) until it commits, so two requests at the same moment can't both create a calendar.
3. If the database is wiped, the app can't find the old calendar and makes a second "Prayers". I accepted that instead of asking for more access.
4. `google_calendar.py` only has 4 calls: create a calendar, get a calendar, insert an event, update an event. There's no code that could touch another calendar.

### 7. Today's prayers without duplicates

1. **Steps in `POST /prayers/today`**:
   a) Work out "today" in the location's time zone.
   b) Calculate with the milestone 2 calculator. Sunrise is skipped, it's not a prayer.
   c) Save 5 rows in `prayer_events`, all `pending`, and commit. Nothing has gone to Google yet.
   d) Make sure the access token works, then find or create the Prayers calendar.
   e) Send each row to Google. After each one, mark it `synced` and commit.
2. **One row per prayer per day**: the table is unique on `(user_id, local_date, prayer)`. Saving uses `INSERT ... ON CONFLICT DO UPDATE`, so a second run updates the same row, even if two requests run at once.
3. **The row's UUID is the Google event ID**. Google lets apps choose event IDs, using the characters 0-9 and a-v. A UUID in hex (0-9, a-f) fits.
   a) Google refuses a second event with the same ID (409 Conflict).
   b) So if a request times out but Google actually saved the event, the retry gets 409, and the app updates the event instead. No copy.
4. **Insert or update**:
   a) Row already sent to this calendar: update (PUT). If Google says 404, insert it again.
   b) Otherwise insert. On 409, update.
5. **`status: confirmed`** in every update. A user-deleted event stays in Google as "cancelled" with its ID still taken. Updating it with `confirmed` brings it back, so it reappears once, not twice. I couldn't test this against the real Google, so it's in the manual checks.
6. **`extendedProperties.private.appEventId`**: the app's UUID on each Google event. Private properties are only visible to this app. Milestone 6 uses it to match Google events back to rows.
7. **Partway failures**: a timeout, 429, or 5xx stops the run. Rows sent so far stay `synced`, the rest stay `pending`, and the answer is 503 with `saved` and `waiting` lists. Running again finishes the job.
8. **Event times**:
   a) Start is the rounded prayer time from the calculator.
   b) End is start plus 15 minutes, added in UTC and converted back. Adding in local time could be off by an hour if a clock change fell inside.
   c) Sent to Google as `dateTime` with the offset plus `timeZone`, like `2026-11-01T17:01:00-05:00` and `America/Toronto`.
9. **Description**: where the time came from, like `Calculated (ISNA, standard Asr)`. When a high latitude rule was used, it's added: `Calculated (ISNA, standard Asr, seventh of the night rule)`.

### 8. Tests

1. **`tests/fake_google.py`**: a fake Google that answers the token endpoint and the Calendar API.
   a) It plugs into the app through `httpx2.MockTransport`, so the app's real code runs and only the network is replaced.
   b) It keeps calendars and events in memory and records every request, including whose token was used.
   c) It checks PKCE for real: the verifier has to hash to the challenge.
   d) It can time out, rate limit, fail with 500, "save the event but lose the answer", expire tokens, kill refresh tokens, and delete calendars or events.
   e) Any URL it doesn't know fails the test, so no test can reach the real Google.
2. **`tests/conftest.py`**: fake settings (a new Fernet key each run), the migrations, emptying tables before each test, the fake Google, the clock, and a `sign_in` helper.
3. **`test_auth.py`**: PKCE and S256, only the 3 scopes, wrong or missing state rejected, a flow can't be used twice, HttpOnly cookie with only its hash saved, sign-out, Origin check.
4. **`test_tokens.py`**: tokens stored encrypted, no token ever in a response, expired token refreshed, dead refresh token gives `needs_reauth`.
5. **`test_google_calendar.py`**: each Google error code turns into the right error, timeouts are temporary, 401 refreshes once.
6. **`test_today_prayers.py`**: 5 events with the right times, 15 minutes, descriptions, and `appEventId`. Running twice gives 5. Failing on the 3rd event (timeout, 429, 500, 503, lost answer) leaves no duplicates and a rerun finishes. Only the Prayers calendar is ever written. A deleted event comes back once.
7. **`test_prayers_calendar.py`**: created once and reused, recreated after deletion with all 5 prayers.
8. **`test_user_isolation.py`**: two users with two cookies. Neither sees the other's events, and Bob's run only uses Bob's token and calendar.
9. **`test_today_prayers_dst.py`**: Toronto on March 7 and 8 and October 31 and November 1, 2026. Every event has the right offset and lasts exactly 15 minutes.
10. **`pytest -m "not database"`** runs only the tests that don't need Postgres. `conftest.py` marks the others automatically.

### 9. How to check it works

1. **Tests**: `pytest` in `backend` with Postgres running. You should see `311 passed`. GitHub Actions runs the same tests with no Google keys.
2. **For real**: follow "Google Calendar" in the README to set up Google Cloud, fill in `.env`, sign in, and run `POST /prayers/today` from `/docs`.
3. **Checks I couldn't automate** (they need the real Google):
   a) Delete one prayer in Google Calendar, run `POST /prayers/today` again, and check it comes back exactly once.
   b) Delete the whole Prayers calendar, run it again, and check a new one appears with all 5 prayers.
