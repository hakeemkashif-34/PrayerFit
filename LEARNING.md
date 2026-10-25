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
   c) Example: Ottawa on October 24, 2026. Solar noon is 12:46:57. Plus 1 minute is 12:47:57, which rounds up to **12:48**. Rounding solar noon alone would give 12:47, so the extra minute is on purpose. Since milestone 4, Dhuhr's event description says this, with that day's solar noon.
   d) Other sites may say 12:46:55 for solar noon. Solar formulas differ by a couple of seconds. That doesn't change the answer.
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
5. **`status: confirmed`** in every update. A user-deleted event stays in Google as "cancelled" with its ID still taken. Updating it with `confirmed` brings it back, so it reappears once, not twice. I couldn't test this against the real Google, so it's in the manual checks. (Since milestone 4, unchanged events aren't sent again, so a deleted event only comes back when it changes. See milestone 4, section 6.)
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

## Milestone 4: Setup questions and nightly updates

### 1. Where things are

1. **`web/`**: the website, React and TypeScript, built with Vite.
   a) `src/App.tsx`: picks the screen: sign in, sign in again, setup, or settings.
   b) `src/api.ts`: every call to the backend, and turning errors into messages.
   c) `src/Setup.tsx` and `src/steps/`: the 3 setup questions, one per page. The settings page reuses the same step components for its Edit buttons, plus the methods and Jumuah steps, which aren't in setup for now.
   d) `src/SettingsPage.tsx`: each saved setting on a card with an Edit button, and Sign out.
   e) `nginx.conf` and `Dockerfile`: build the site, then serve it with nginx, which also passes API calls to the backend.
   f) `tests/`: Playwright tests with a mocked API (`mock-api.ts`).
2. **`backend/app/geo/`**: finding places.
   a) `photon.py`: address suggestions as the user types.
   b) `timezones.py`: location to time zone, offline.
   c) `overpass.py`: masjids near a location.
   d) `throttle.py`: spaces out calls to those free services.
3. **`backend/app/user_settings.py`**: reads and saves setup answers, and decrypts the address.
4. **`backend/app/routers/settings.py`**: the setup and settings endpoints.
5. **`backend/app/calendar_window.py`**: works out the next 14 days of events and sends only the ones that changed.
6. **`backend/app/nightly.py`** and **`backend/app/worker.py`**: the nightly job and the worker service that runs it.
7. **`backend/app/http_client.py`**: was `google_http.py`. Renamed because OpenStreetMap calls use it too.
8. **`backend/alembic/versions/0002_settings_masjids_jobs.py`**: the new tables.

### 2. One site: nginx in front of everything

1. **The problem**: the session cookie is `SameSite=Lax`, and the backend refuses any POST whose `Origin` isn't `APP_ORIGIN`. If the website ran on port 5173 and the API on port 8000, they'd be different origins, and every save would get 403.
2. **The fix**: nginx serves the website and passes API calls on, all from `http://localhost:8000`.
   a) `/api/me` goes to the backend as `/me`. The trailing slash in `proxy_pass http://backend:8000/;` strips `/api`.
   b) `/auth/...` goes to the backend unchanged. That's why the Google redirect URI didn't have to change.
   c) Anything else gets `index.html`, the website.
3. The backend isn't published to the host any more. Only nginx is.
4. Uvicorn runs with `--root-path /api`, so `/api/docs` knows its JSON is at `/api/openapi.json`.
5. After sign-in, the callback sends the browser to `/` (the website) instead of `/docs`. A failed sign-in goes to `/?sign_in_error=cancelled` (or `expired`, `state`, `google`). Only these fixed codes go in the URL, and the website turns each into its own message, so nobody can make a link that shows their own text on the sign-in page.
6. Every 401 now has a `reason`: `not_signed_in` shows **Sign in with Google**, and `google_sign_in_expired` shows **Sign in again**, not an error.

### 3. Database

1. **`user_settings`**: one row per user.
   a) The address the user picked and its coordinates are both **encrypted** with the same Fernet key as the Google tokens. Coordinates point to a home just as well as an address does, so they're encrypted too.
   b) The time zone is plain text. The nightly job needs it to know when 3:00 am is.
   c) Each answer is empty until its step is saved. `missing_steps` lists what's left: `address`, `masjid`, and `weekly` (not for "I pray at home").
   d) `method` and `asr_method` stay empty until changed on the settings page. Empty means the defaults, ISNA and standard (`method_of` and `asr_method_of`). Jumuah starts with no masjids. Setup doesn't ask about either for now, but the code and anything saved are kept.
2. **`masjids`**: OpenStreetMap masjids (with `osm_type` and `osm_id`) and typed-in ones (with `created_by_user_id`).
   a) OpenStreetMap masjids are public, so every user can see them. Typed-in ones are only shown to the user who typed them.
   b) Nothing is made up. A masjid with no name on OpenStreetMap has an empty name and shows as "No name on OpenStreetMap". The address is only what OpenStreetMap's `addr:*` tags say. No times are stored yet.
   c) OSM IDs are only unique within a type (a node and a way can share a number), so the unique key is `(osm_type, osm_id)`.
3. **`weekly_masjid_prayers`**: 7 rows per user, one per weekday, each with 5 true/false columns. 0 is Monday, the same as Python's `date.weekday()`.
4. **`user_jumuah_masjids`**: links a user to each Jumuah masjid. A user can have several, or none.
5. **`geocode_cache`**, **`overpass_cache`**, **`api_throttle`**: see sections 4 and 5.
6. **`nightly_jobs`**: see section 7.
7. **New `prayer_events` columns**: `place` (`home` or `masjid`), `masjid_id`, `summary` (the title), `description`, and `synced_hash`.

### 4. Addresses: Photon

1. **Why Photon**: setup shows suggestions in a dropdown as the user types. Nominatim, OpenStreetMap's main address search, bans that in its usage policy. **Photon** (`photon.komoot.io`) searches the same OpenStreetMap data and is built for search-as-you-type. It's free, and asks apps to be fair.
2. **Being fair to Photon**:
   a) **Wait for a pause**: the website only searches once typing stops for 400 ms. Each keystroke cancels the waiting timer, and also cancels a search already on its way (`AbortController`), so typing "200 Kanata" sends 1 request, not 10.
   b) **At least 3 characters**: fewer gets no search, on the website and again on the backend.
   c) **At most 5 suggestions**: the backend asks Photon for 10 and keeps 5.
   d) **Favour Canada**: Photon is asked to prefer results near the middle of Canada, with a wide radius. Then the backend moves Canadian results to the top, keeping Photon's order otherwise. That's why it asks for 10: a Canadian match in 7th place still makes the top 5.
   e) **Cache**: each answer is kept for 7 days. The same text, with different spacing or capitals, is only sent once.
   f) **Through our backend**: the browser never calls Photon. Every request comes from the backend with the User-Agent `MuslimCalendar/0.4 (+mailto:<OSM_CONTACT_EMAIL>)`.
   g) **Spaced out**: calls from the whole app are at least 0.25 seconds apart (`throttle.py`).
   h) **Credit**: OpenStreetMap's licence (the ODbL) requires credit wherever its data is shown. One small grey "© OpenStreetMap contributors" link sits in the footer of every page that uses it: setup and the settings page. The landing page shows no OpenStreetMap data, so it has no footer.
   i) **No postal codes**: suggestions and the saved address leave out the postal code. OpenStreetMap's Canadian postal codes are often wrong (it showed the wrong one for my address), and prayer times only need the location. Postal code areas Photon sends as places are dropped too. The cache key got a `v2` so old cached labels with postal codes are never shown.
3. **`throttle.py`**: the last call time lives in one Postgres row.
   a) A caller locks the row (`SELECT ... FOR UPDATE`), waits until enough time has passed, writes the new time, and commits.
   b) Anyone else blocks on the lock until then.
   c) Using Postgres instead of a Python variable means the limit holds across every process. Overpass uses the same code with 1 second.
4. **Picking saves it**: `POST /setup/location/suggest` returns each suggestion with its place in the list. Picking one calls `PUT /settings/location` with the text and that number. The backend reads the answer from the cache, so the saved location is exactly what the user saw, and the browser never sends coordinates.
5. **The dropdown is a combobox**: the input has `role="combobox"` and the list has `role="listbox"`, so screen readers announce it. Up and down arrows move through the list, Enter picks, and Escape closes it.
6. **Keeping the address private**:
   a) It's sent in the request body, never the URL, so it can't show up in access logs.
   b) httpx2 logs every URL at INFO, and a Photon URL contains what was typed. `http_client.py` sets the `httpx2` and `httpcore2` loggers to WARNING.
   c) Error messages never include it. A timeout error from httpx can include the URL, so the app shows its own message instead.
   d) The cache key is an **HMAC** of the text (a hash mixed with the secret key), and the cached answer is encrypted. Without the key, someone can't check a guess like "is 123 Main St in here?" Partly typed addresses are cached too, so this matters even more than before.
   e) `test_address_never_shows_up_in_logs` captures every log line during a full setup and checks the address isn't there. I checked the test works by turning the httpx2 logger back on: it failed.
7. **Failure logs**: when Google, Photon, or Overpass fails, `log_failure` in `http_client.py` writes one line like `Overpass failed: status 504 after 41.2 s` or `Photon failed: timeout after 10.0 s`.
   a) The reason is only the status code, "timeout", or "connection error". Never the error's own text, because httpx2 puts the URL in it, and the URL holds the address or location.
   b) Google's 404 and 409 answers aren't logged. The code expects them (a deleted calendar, an event that already exists).
   c) Tests check each kind of failure is logged with its time, and that no address, coordinates, or calendar ID is in the log.

### 5. Time zone and nearby masjids

1. **Time zone**: `timezonefinder` has the world's time zone borders inside the package, so it works offline and costs nothing. Ottawa gives `America/Toronto`, Regina gives `America/Regina` (no daylight saving).
2. **Overpass** is OpenStreetMap's free query service. The query asks for every node, way, or relation tagged `amenity=place_of_worship` and `religion=muslim` near a point. `out center` gives a middle point for buildings drawn as shapes.
3. **Privacy and caching with a grid**:
   a) The location is rounded to 2 decimal places (about 1 km). Overpass only ever gets that rounded point, never the home.
   b) The query radius is 17 km around the cell's centre. Any point in a cell is under 0.8 km from the centre, so every home in the cell gets its full 15 km.
   c) Each cell's results are cached for 30 days, since masjids rarely change. Neighbours in the same cell share one Overpass call.
   d) The exact distance is worked out on the server from the real location, kept if 15 km or less, and sorted closest first.
4. **Distance** is the haversine formula: the straight-line distance over the Earth's curve. Ottawa to Toronto comes out at about 352 km, which the tests check. No ratings, just name and distance.
5. If every Overpass server is busy or down, the user sees "OpenStreetMap's masjid search is busy right now. Try again in a few minutes." (see point 7).
6. **Overpass gets 60 seconds**: on my laptop, a real Overpass query for Kanata took 40.5 seconds and still worked. Google and Photon keep the usual 10 seconds, so Overpass passes its own `timeout=60` on that one request.
   a) The chain has to wait longest at the front: the browser waits forever, nginx waits 120 seconds for `/api/`, and the backend gives each Overpass server up to 60 and all of them together up to 100. If nginx waited less than the backend, the user would get nginx's error even though the backend was about to answer.
   b) While it waits, the masjid step says "Searching for masjids nearby. This can take up to a minute."
   c) `test_overpass_call_uses_a_60_second_timeout` reads the timeout httpx2 put on the actual request. I checked it fails when the `timeout=60` is taken out.

7. **Setup never waits on Overpass**: on my laptop, overpass-api.de answered 502 in 0.4 s and overpass.private.coffee didn't answer within 60 s. Public servers go down, so:
   a) **Backup servers**: `OVERPASS_URLS` in `.env` is a list, tried in order. A 429, a 5xx, a timeout, or a connection error moves on to the next server. A 400 doesn't, because it means our query is wrong and every server would say the same. The default list is the public servers on the OpenStreetMap wiki: overpass-api.de (FOSSGIS), maps.mail.ru (VK Maps), and overpass.private.coffee.
   b) **A time budget**: each server gets up to 60 seconds, but all of them together get at most 100, so the backend always answers before nginx's 120. A server isn't asked with under 5 seconds left.
   c) **Started early**: saving the location adds a FastAPI background task that runs the masjid search after the response is sent. By the time the user has read the masjid question, it's usually cached. The task gets its own database session and HTTP client, because the request's are closed by then. A failure is only logged.
   d) **One search per cell**: a Postgres advisory lock on the cell (`app/locks.py`, the same helper the calendar uses per user). If the masjid page asks while the background search is running, it waits and then reads the cache instead of asking Overpass again. If the search it waited for failed, it says so straight away instead of starting another one that could outlast nginx.
   e) **The fallback choices always show**: "My masjid isn't listed" and "I pray at home" are on the page while it searches and after a failure, with a "Search again" button. Setup can always carry on.

### 6. The 14-day window

1. **What it does** (`refresh_calendar`):
   a) Work out each prayer for today plus the next 13 days with the milestone 2 calculator.
   b) Pick home or masjid for each prayer from the weekly grid.
   c) Save each event, then send the ones that changed to Google.
2. **Days, not hours**: the dates are `today + timedelta(days=n)`. Adding days to a date moves the calendar date. On November 1, 2026 (a 25-hour day), adding 24 hours to midnight would land on 11 pm the same day, and a day would repeat. The tests check the window across November 1 and March 8.
3. **Titles**: `Fajr at home` or `Dhuhr at KMA`.
   a) The masjid part is the short name if there is one, then the OpenStreetMap name, then "the masjid".
   b) The short name is per user, so one person's "KMA" doesn't change anyone else's calendar.
4. **Descriptions**:
   a) Line 1: where the time came from, like `Calculated (ISNA, standard Asr)`.
   b) Masjid events add: "Iqamah times not added yet, so this is the calculated prayer time." Iqamah times come in milestone 5. Until then nothing invents one.
   c) Dhuhr adds why it's after solar noon, with that day's solar noon, like `(12:46:57 pm)`.
5. **Only send what changed** (`synced_hash`):
   a) After Google confirms an event, the app saves a SHA-256 hash of exactly what it sent.
   b) Next time, it builds the event again and hashes it. Same hash means nothing changed, so it isn't sent.
   c) Ticking Asr on Tuesdays sends 2 events, not 70. Saving the same answer twice sends nothing.
6. **Leave the past alone**: a row that already started is skipped, even if the settings changed. It's history.
7. **One update per user at a time**: the website and the nightly job could update the same user at once. `user_lock` takes a Postgres advisory lock (a lock on a number, not a row) for that user.
   a) It's held on its own connection, because the update commits many times, and a normal transaction lock would end at the first commit.
8. **Moving**: if the time zone changes, `ensure_prayers_calendar` PATCHes the calendar's `timeZone`. It's the same calendar, not a new one.
9. **When it runs**:
   a) **Fill my calendar** fills all 14 days, while the user waits (about 10 to 20 seconds with real Google).
   b) Each Edit after setup updates the calendar straight away.
   c) If Google fails partway, the settings are still saved. The website shows "Some prayers haven't reached Google Calendar yet" with **Try again** (`POST /calendar/sync`), and the nightly job retries too.
10. **A trade-off**: in milestone 3, running `POST /prayers/today` again sent all 5 events every time, which also brought back an event the user deleted in Google. Now unchanged events aren't sent, so a deleted event only comes back when its details change. Noticing edits and deletions made in Google is milestone 6 (two-way sync).
11. **`POST /prayers/today`** no longer takes a location. It uses the saved settings and answers 409 "Finish setup first" before setup is done.

### 7. The nightly job

1. **Its own service**: `worker` in Docker Compose runs `python -m app.worker`. Same image as the backend, different command. It checks every 60 seconds.
2. **3:00 am in each user's own time zone**:
   a) A job is due once the user's local clock reads 3:00 or later.
   b) Not 2:00 am: on March 8, 2026, Toronto's clocks jump from 2:00 to 3:00, so 2:00 to 2:59 never happens. 3:00 always does in Toronto.
   c) Comparing the clock reading instead of building a "3:00 am" time also handles places where 3:00 itself is skipped. Helsinki jumps from 3:00 to 4:00, so its job runs at 4:00.
   d) On November 1, 1:30 am happens twice, and both are still before 3:00.
3. **Never twice**:
   a) Each job is saved before it runs, with the ID `nightly:{user_id}:{date}`. Saving it again does nothing (`INSERT ... ON CONFLICT DO NOTHING`).
   b) A worker claims the job with one `UPDATE ... WHERE status = 'pending'`. Postgres only lets one of two workers change that row, so only one runs it. A test starts 2 workers at the same moment.
   c) Even a repeat would be safe: fixed event IDs and the hash check mean nothing is duplicated.
4. **Catching up**: when the worker starts, the first check finds today's job (if it's past 3:00) and runs it.
   a) Only the newest night runs, because it rolls the whole window forward. Older unfinished jobs are marked `skipped`.
   b) A night before the user finished setup is never run. Finishing setup already filled the calendar.
5. **Crashes**: a job still `running` after 15 minutes means its worker died, so it goes back to `pending`.
6. **Expired sign-in**: the job is marked `needs_sign_in` and the worker moves on to the next user. After the user signs in again, the next check runs it. A test has 3 users where the middle one's sign-in expired.
7. **Google errors**: the job is `failed` and tries again 15 minutes later, up to 5 times a night.
8. **One user's bug can't stop everyone**: any other error is caught, logged, and marked `failed`.
9. **Never deletes**: the Calendar client still has no delete call. Past prayers stay in Google.
10. **`run-now`**: runs today's job straight away, using the same job IDs. A second run says "Already ran today". `--force` runs it again, which sends 0 events if nothing changed.

### 8. The website

1. **No router library**: the app only has 4 screens, so `App.tsx` keeps a `view` in React state and switches on it.
2. **Landing page**: the welcome on the left and the sign-in card on the right, using a CSS grid with 2 columns. Below 760 px wide, it's 1 column, so they stack.
3. **One question per page**: `Setup.tsx` keeps which question it's on. It starts at the first unanswered one.
   a) **Back** goes to the previous question with its answer kept.
   b) A saved location shows with a **Next** button, so going back and forward doesn't search again.
   c) After the masjid question, "I pray at home" skips the grid.
   d) Straight after the last answer, the website calls `POST /setup/finish` and shows "Filling your Prayers calendar…". There's no extra button to press.
   e) **Matches the landing page**: on a computer, a "Setup" heading and the 3 steps (Location, Masjid, Weekly prayers) are on the left, with the current one highlighted (`aria-current="step"`, so screen readers say it too) and finished ones ticked. The question is on the right. On a phone the list is hidden and "Setup · Step X of 3" shows at the top instead. Weekly prayers is crossed out for "I pray at home".
   f) **Just the question**: the location page only says "What's your location?". The box still has a label for screen readers, hidden on screen.
4. **Same code for setup and Edit**: each step takes `onSaved`, and a `page` flag that makes its question the page's main heading in setup. The settings page shows the step inside the card being edited.
5. **The closest masjid** is first in the list, with a "Closest" badge and a thicker border.
6. **Short name**: belongs to one masjid, so picking a different masjid clears it. Otherwise "Dhuhr at KMA" would show for Stittsville. Playwright caught this.
7. **Picking a masjid after "I pray at home"** opens the weekly grid straight away, with no Cancel, since the calendar needs it.
8. **Font**: Plus Jakarta Sans, installed from npm (`@fontsource-variable/plus-jakarta-sans`). Vite copies the font files into `dist/assets/`, so our own nginx serves them. Nothing loads from Google Fonts, which would tell Google about every visitor. It's a variable font: one file covers every weight from 200 to 800. Headings use 800 with slightly tighter letter spacing, so they stand out from the 400 body text. A Playwright test checks the font is used and only comes from our own site.
9. **Phones**: one column, tap targets at least 48 px tall. The weekly grid has the 5 prayers as rows and the 7 days as columns, with short day names (Mon, Tue...), so it still fits on a phone without scrolling sideways.
10. **Sign out** posts to `/auth/logout` and goes back to the sign-in screen.

### 9. Tests

1. **`tests/fake_osm.py`**: a fake Photon and Overpass, like the fake Google. It checks the User-Agent, the Canada bias, and the query. Photon answers places whose words start with what was typed. Overpass answers only masjids within the query's radius. Any URL it doesn't know fails the test, so no test reaches the real Photon.
2. **`tests/setup_helpers.py`**:
   a) `save_setup` writes a finished setup straight into the database, for tests that only care what happens after setup.
   b) `setup_through_api` answers the 3 questions through the real endpoints, then finishes.
3. **`test_geo.py`**: Photon suggestions with Canada first, at most 5, nothing sent under 3 characters, duplicates dropped, its cache, failures with no address in the message, the spacing between calls, time zones for 5 cities, distances, sorting, the 15 km cut-off, the rounded cell, and the Overpass cache.
4. **`test_settings.py`**:
   a) Each answer saves, and setup is only the 3 questions, with ISNA, standard, and no Jumuah.
   b) The address is encrypted in the raw database row and never logged.
   c) The time zone comes from the location.
   d) A typed-in masjid saves.
   e) The weekly grid saves all 7 days.
   f) "I pray at home" skips the grid.
   g) Everything is scoped to one user. Bob can't see or pick Alice's typed-in masjid.
5. **`test_calendar_window.py`**:
   a) 70 events with no duplicates.
   b) "at home" and "at KMA" titles.
   c) The iqamah note.
   d) The Dhuhr line.
   e) A change only sends the future events that changed.
   f) Past events stay.
   g) Google failing partway finishes later without duplicates.
   h) The next day adds 5 events and deletes nothing.
6. **`test_window_dst.py`**: the 14-day window across November 1 and March 8. Each day has its 5 prayers, with the right offset, and each event lasts exactly 15 minutes.
7. **`test_nightly.py`**:
   a) 3:00 am in each time zone, including both daylight saving days and Helsinki.
   b) Once per user per day, even when started twice or by 2 workers at once.
   c) A crashed job reruns.
   d) A missed night catches up.
   e) One expired sign-in doesn't stop the others.
   f) Retries and the 5-attempt limit.
   g) Fixing times that changed.
   h) `run-now`.
8. **Playwright** (`web/tests/`): the landing page (side by side on a computer, stacked on a phone), "Sign in again", the full setup flow (typing with one search per pause and none under 3 characters, picking a suggestion, the closest masjid highlighted, a short name, the grid with prayers as rows, finish), Back, the arrow keys, "I pray at home", a typed-in masjid, editing the location and other settings, Cancel, and Sign out. Each test runs on a desktop and a Pixel 7 sized screen.
9. **GitHub Actions** runs both: the `backend` job (pytest with Postgres) and the `web` job (type check and Playwright). Neither has any real keys.

### 10. How to check it works

1. **Tests**: `pytest` in `backend` (`450 passed`) and `npx playwright test` in `web` (`58 passed`).
2. **For real**: follow "Go through setup" in the README with your test Google account. The Prayers calendar should have 70 events.
3. **Change a setting**: tick one more prayer on one weekday. The message should say 2 events were sent, and only those 2 change in Google Calendar.
4. **Nightly job**: `docker compose exec worker python -m app.worker run-now --email you@gmail.com`, then again, then with `--force`. Still 70 events.
5. **Checks I couldn't automate** (they need the real services):
   a) The real Photon suggestions for your address, and the masjids near it on the real Overpass. Some may have no name on OpenStreetMap.
   b) That nginx starts and passes `/api` and `/auth` through. I checked the Compose file with `docker compose config` and the `--root-path` setup with uvicorn directly, but there was no Docker engine where I built this.
