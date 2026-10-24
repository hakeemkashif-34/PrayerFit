# Muslim Calendar

A website that keeps your prayer times up to date in your Google Calendar.

See [Muslim_Calendar_App.md](Muslim_Calendar_App.md) for the full product description and [LEARNING.md](LEARNING.md) for how each part works.

## Stack

1. Website: React and TypeScript, built with Vite, served by nginx
2. Backend: Python and FastAPI
3. Database: Postgres, with SQLAlchemy and Alembic for migrations
4. Nightly job: its own worker service, same code as the backend
5. Sign-in: Google, done on the server with PKCE
6. Addresses and nearby masjids: OpenStreetMap's free Nominatim and Overpass services
7. Runs with Docker Compose
8. Tests: pytest for the backend, Playwright for the website, both run by GitHub Actions on every push and pull request

## Run it with Docker

```bash
cp .env.example .env        # then edit the values
docker compose up --build
```

Open http://localhost:8000. That's the website.

Docker Compose starts 4 services:

| Service | What it does |
|---|---|
| `web` | nginx. Serves the website and passes `/api/...` and `/auth/...` to the backend. The only service the browser talks to. |
| `backend` | FastAPI. Runs the database migrations (`alembic upgrade head`) before it starts. |
| `worker` | The nightly job. Checks every minute whose 3:00 am has come. |
| `db` | Postgres. |

The website and the API share one address (`http://localhost:8000`), so the browser treats them as the same site. That's what lets the session cookie and the Origin check work.

Open http://localhost:8000/api/health. You should see `{"status":"ok","database":"ok"}`.

To see the error case, stop the database with `docker compose stop db` and refresh. You should get a 503 error and `{"status":"error","database":"unreachable"}`. Start it again with `docker compose start db`.

http://localhost:8000/api/docs lists every endpoint and lets you try them in the browser.

## Prayer times

Open http://localhost:8000/api/prayer-times?latitude=45.4215&longitude=-75.6972&date=2026-10-24 to get Ottawa's prayer times for that day.

| Parameter | Required | Default | Example |
|---|---|---|---|
| `latitude` | yes | | `45.4215` |
| `longitude` | yes | | `-75.6972` |
| `date` | no | today in that time zone | `2026-10-24` |
| `method` | no | `isna` | `isna`, `mwl`, `egyptian`, `karachi`, `umm_al_qura` |
| `asr_method` | no | `standard` | `standard`, `hanafi` |
| `timezone` | no | `DEFAULT_TIMEZONE` from `.env`, or `America/Toronto` | `America/Edmonton` |

Every time comes back with where it came from (`"source": "calculated"`, the method, and the Asr method).

## Google Calendar

I sign in with Google and the app keeps the next 14 days of prayers in a calendar called "Prayers" that it creates in my Google account. It only asks for `openid`, `email`, and `calendar.app.created`, which lets it manage calendars it made itself and nothing else. No Gmail, and it can't see my other calendars.

### 1. Set up Google Cloud (once)

1. Go to https://console.cloud.google.com and create a project, for example "Muslim Calendar".
2. In **APIs & Services > Library**, search for **Google Calendar API** and click **Enable**.
3. Open **Google Auth Platform** (or **APIs & Services > OAuth consent screen**) and click **Get started**.
   a) App name: Muslim Calendar. User support email: your email.
   b) Audience: **External**.
   c) Contact email: your email. Agree and create.
4. In **Audience**, leave the publishing status as **Testing**. Under **Test users**, add the Google account you'll sign in with.
5. In **Data Access**, click **Add or remove scopes** and add:
   a) `openid`
   b) `.../auth/userinfo.email`
   c) `https://www.googleapis.com/auth/calendar.app.created` (paste it under "Manually add scopes" if it's not in the list)
6. In **Clients**, click **Create client**.
   a) Application type: **Web application**.
   b) Authorized redirect URIs: `http://localhost:8000/auth/google/callback`
   c) Click **Create** and copy the client ID and client secret. Google only shows the secret once, so save it (or download the JSON).

The redirect URI is the same as in milestone 3. nginx passes `/auth/...` straight to the backend, so nothing in Google Cloud has to change.

In Testing mode, Google expires refresh tokens after 7 days. When that happens the website shows a **Sign in again** button instead of an error. That's expected, not a bug.

### 2. Fill in `.env`

```bash
GOOGLE_CLIENT_ID=<the client ID>.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=<the client secret>
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback
TOKEN_ENCRYPTION_KEY=<generated, see below>
APP_ORIGIN=http://localhost:8000
COOKIE_SECURE=true
SESSION_DAYS=30
OSM_CONTACT_EMAIL=<your email>
```

`OSM_CONTACT_EMAIL` goes in the User-Agent of every request to Nominatim and Overpass. Their usage policies ask apps to give a way to contact the owner.

Make the encryption key with:

```bash
docker compose build backend
docker compose run --rm --no-deps backend python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

The same key encrypts Google tokens and home addresses. If it's lost or changed, everyone has to sign in and enter their address again.

### 3. Go through setup

1. `docker compose up --build`
2. Open http://localhost:8000 and click **Sign in with Google**.
3. Pick your test account. Google warns that the app isn't verified. Click **Continue**. Leave the calendar box ticked and allow.
4. You land back on the website, on step 1 of setup.
5. **Address**: type it and press **Find address**. Check the place it found, then press **Yes, that's it**. The time zone comes from the location.
6. **Method**: ISNA and standard Asr are picked already. Press **Save**.
7. **Main masjid**: pick one from the list (closest first, within 15 km), type one in with **My masjid isn't listed**, or pick **I pray at home**. You can give it a short name like `KMA` for the calendar.
8. **Weekly grid**: tick the prayers you usually pray at the masjid, Monday to Sunday. This step is skipped if you pray at home.
9. **Jumuah**: tick every masjid you can go to for Jumuah.
10. Press **Fill my calendar**. It takes about 10 to 20 seconds.
11. Open Google Calendar. The **Prayers** calendar has today and the next 13 days: 70 events, like `Fajr at home` and `Dhuhr at KMA`. Each description says where the time came from. Masjid events also say the iqamah times aren't added yet, so they show the calculated time.

### 4. Change a setting

On the settings page, press **Edit** next to any setting, change it, and press **Save**. The message at the top says how many events were sent to Google. Only future events that changed are sent. Past events are never touched. For example, ticking Asr on Tuesdays sends 2 events (the 2 Tuesdays in the window), not 70.

If you move to another time zone, the Prayers calendar's time zone changes too.

## Nightly job

The `worker` service updates every user's calendar at 3:00 am in their own time zone. It adds the newest day, fixes any times that changed, and never deletes past prayers. Not 2:00 am, because 2:00 am doesn't exist on the spring daylight saving day.

Each job is saved with an ID like `nightly:<user id>:2026-10-24` before it runs, so a retry or a second worker can't run it twice. If the worker was off at 3:00 am, it catches up when it starts. If one user's Google sign-in expired, their job is marked `needs_sign_in` and everyone else still gets updated.

To run it now, for testing:

```bash
docker compose exec worker python -m app.worker run-now --email you@gmail.com
```

It prints something like `nightly:...:2026-10-24: done, 0 events sent to Google`. Run it again and it says `Already ran today. Add --force to run it again.` With `--force` it runs again and sends 0 events when nothing changed. Leave out `--email` to run it for every user.

See the jobs with:

```bash
docker compose exec db psql -U muslim_calendar -c "SELECT id, status, attempts, events_sent FROM nightly_jobs ORDER BY created_at"
```

## Endpoints

Through nginx, every endpoint below is under `/api` (like `/api/me`), except the `/auth/...` ones.

| Endpoint | What it does |
|---|---|
| `GET /auth/google/login` | Starts sign-in (open it in the browser) |
| `GET /auth/google/callback` | Google sends you back here, then to the website |
| `POST /auth/logout` | Signs out |
| `GET /me` | Who's signed in, whether Google needs a new sign-in, and whether setup is done |
| `GET /settings` | Your saved setup answers |
| `POST /setup/address/search` | Looks up an address with Nominatim. Saves nothing |
| `PUT /settings/address` | Saves the confirmed address (encrypted) and its time zone |
| `PUT /settings/methods` | Saves the calculation method and Asr method |
| `GET /masjids/nearby` | Masjids within 15 km from Overpass, closest first |
| `PUT /settings/main-masjid` | Saves the main masjid, a typed-in one, or "I pray at home" |
| `PUT /settings/weekly` | Saves the weekly grid (7 days) |
| `PUT /settings/jumuah` | Saves the Jumuah masjids |
| `POST /setup/finish` | Finishes setup and fills the next 14 days |
| `POST /calendar/sync` | Sends anything still waiting. Safe to run again |
| `POST /prayers/today` | Updates today's 5 prayers from your saved settings. Safe to run again |
| `GET /prayers/today/events` | Your saved events for today |

POST and PUT requests need an `Origin` header matching `APP_ORIGIN`. Browsers send it on their own. With curl, add `-H "Origin: http://localhost:8000"`.

## Run the tests

### Backend

The backend tests need a real Postgres. The easiest way is to start only the database from Docker Compose.

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

Use the same user, password, and database name as in your `.env`. You should see `416 passed`.

The tests never call the real Google, Nominatim, or Overpass. They use fakes (`tests/fake_google.py` and `tests/fake_osm.py`) and fake keys, so no real settings are needed.

To run only the tests that don't need the database: `pytest -m "not database"` (`265 passed, 151 deselected`).

When you're done, stop Postgres with `docker compose down`.

### Website

```bash
cd web
npm ci
npx playwright install chromium   # once
npx playwright test
```

You should see `30 passed`: 15 tests, each on a desktop and a phone-sized screen. The tests mock the API, so the backend doesn't need to be running.
