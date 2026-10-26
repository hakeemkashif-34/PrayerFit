# Muslim Calendar

A website that keeps your prayer times up to date in your Google Calendar.

See [Muslim_Calendar_App.md](Muslim_Calendar_App.md) for the full product description and [LEARNING.md](LEARNING.md) for how each part works.

## Stack

1. Website: React and TypeScript, built with Vite, served by nginx
2. Backend: Python and FastAPI
3. Database: Postgres, with SQLAlchemy and Alembic for migrations
4. Nightly job: its own worker service, same code as the backend
5. Sign-in: Google, done on the server with PKCE
6. Addresses and masjids: the free Photon search, built on OpenStreetMap data
7. Masjid times: each masjid's public MAWAQIT page, with calculated times when it can't be read
8. Drive times: OpenRouteService's free plan (no live traffic)
9. Runs with Docker Compose
10. Tests: pytest for the backend, Playwright for the website, both run by GitHub Actions on every push and pull request

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
| `worker` | Background jobs, checked every minute: the nightly job, reading MAWAQIT, and queued calendar updates. |
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

I sign in with Google and the app keeps the next 14 days of prayers in a calendar called "Prayers" that it creates in my Google account. It only asks for `openid`, `email`, `calendar.app.created`, and `calendar.freebusy`. `calendar.app.created` lets it manage calendars it made itself and nothing else. `calendar.freebusy` lets it see when I'm busy on Friday, so it can pick a Jumuah that fits, but never what my events are. No Gmail, and it can't read my other calendars.

The app only checks my primary calendar for busy times. Checking my other calendars would need one more scope (`calendar.calendarlist.readonly`, to find them), so it doesn't. Busy times are never saved. If Google doesn't answer, Jumuah is picked as if Friday were free, and the calendar update carries on.

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
   d) `https://www.googleapis.com/auth/calendar.freebusy` (same)

If your project was set up before milestone 5, go to **Google Auth Platform > Data Access** and add d). Then everyone who signed in before sees a **Sign in again** banner on Settings. Until they sign in again, Jumuah is picked as if their Friday were free.
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

`OSM_CONTACT_EMAIL` goes in the User-Agent of every request to Photon. It asks apps to give a way to contact the owner.

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
4. You land back on the website, on page 1 of 2. The 2 pages are listed on the left (on a phone, "Setup · Step 1 of 2" is at the top).
5. **Required** (page 1) has 4 questions on one page, all shown at once:
   a) **What's your location?** Start typing your address. Suggestions show up in a dropdown once you stop typing. Pick yours. It's saved right away, and the time zone comes from it. Postal codes aren't shown or saved, since OpenStreetMap's are often wrong in Canada.
   b) **Which masjid do you usually go to?** Start typing its name. Suggestions show the masjid's name and its distance from home, closest first. If yours doesn't come up, type its address instead and pick that. Press **I pray at home** if you do: every prayer is at home and there's no weekly grid.
   c) **Which prayers do you usually pray at the masjid?** Tick them in the grid: prayers down the side, Monday to Sunday across the top. Anything left unticked is at home.
   d) **Generally speaking, which Jumuah would you like to attend?** Each Jumuah slot (1st, 2nd, 3rd) at your masjid is a block on a simple midday calendar, from its start to its end (the masjid's Jumuah length, or 45 minutes when it isn't set). The times are this week's, only as an example: the pick is saved as "the 2nd Jumuah", not a clock time. It doesn't show a date or your busy times. Click a block to pick it. The 1st Jumuah is picked for you. If you pray at home, or your masjid has no Jumuah times yet, this question is skipped and the 1st Jumuah is saved (when there's a Jumuah masjid to save it for).
   Press **Next** to save the masjid, the grid, and the Jumuah pick.
6. **Optional** (page 2): a short name like `KMA`, how many minutes before iqamah and before Jumuah you want to arrive (whole numbers from 0 to 60, 5 by default), and a colour for prayer blocks and for drive blocks (Basil by default). **Back** goes to page 1 without losing anything typed here. **Skip** (top right) saves the defaults.
7. Press **Finish** (or **Skip**). Nothing is written to Google Calendar before this. A new tab opens and says "Adding your prayers to Google Calendar..." while the calendar fills, in about 10 to 20 seconds, then shows Google Calendar for the account you signed in with. The first tab goes to the Settings page. If the update fails, the new tab shows the error with a link back to Settings, and Settings shows it too, with **Try again**. If your browser blocks the new tab, Settings says so, and **Open Google Calendar** is right there.
8. Calculated times always use ISNA with standard Asr. Your main masjid becomes your Jumuah masjid. On the Settings page you can remove it or add others. Praying at home means no Jumuah masjids.
9. Every event the app makes is private, so people you share your calendar with only see "busy".
10. In Google Calendar, the **Prayers** calendar has today and the next 13 days, like `Fajr at home` and `Dhuhr at KMA`. Each description says where the time came from. Until your masjid is linked to MAWAQIT (below), masjid prayers use the calculated time and say the iqamah isn't available.

### 4. Change a setting

Coming back to the website later opens the **Settings** page. It never sends you to Google Calendar on its own. Press **Open Google Calendar** to go there. Settings is one card with 2 sections. **Required** has your location, main masjid, weekly prayers, and your Jumuah pick (the same calendar view as setup). **Optional** has your Jumuah masjids, the short name, both "how early" times, and both colours. Press **Edit** next to any one of them, change it, and press **Save**. The message at the top says how many events were sent to Google. Only future events that changed are sent. Past events are never touched. For example, ticking Asr on Tuesdays sends 2 events (the 2 Tuesdays in the window), not 70.

If you move to another time zone, the Prayers calendar's time zone changes too.

## Masjid times from MAWAQIT

Masjid times come from each masjid's public page on [MAWAQIT](https://mawaqit.net). Linking a masjid to its page is a command on the server, not a website button, so a user can't link the wrong page for everyone.

1. Find the masjid's ID:

   ```bash
   docker compose exec backend python -m app.admin list-masjids
   ```

   Each line has the ID, the name, its MAWAQIT link (or "not linked"), and how many users picked it. A masjid only shows up once someone has picked it in setup.

2. Link it to its MAWAQIT page:

   ```bash
   docker compose exec backend python -m app.admin link-mawaqit --masjid <masjid id> --url https://mawaqit.net/en/<masjid page>
   ```

   Only `https://mawaqit.net` links are accepted, and only the page name from the link is saved. The widget link (`https://mawaqit.net/en/w/<masjid page>`) works too. KMA's page is `https://mawaqit.net/en/kma-masjid-ottawa`.

3. The worker reads the page within a minute, then at most once every 6 hours. To read it now:

   ```bash
   docker compose exec backend python -m app.admin fetch-mawaqit --masjid <masjid id>
   ```

   Then `docker compose exec worker python -m app.worker run-now --force` to update calendars straight away.

4. To stop using a page: `python -m app.admin unlink-mawaqit --masjid <masjid id>`. Calendars go back to calculated times.

5. To set how long a masjid's Jumuah is, from the khutbah to the end of the prayer (whole minutes from 15 to 90):

   ```bash
   docker compose exec backend python -m app.admin set-jumuah-length --masjid <masjid id> --minutes 40
   ```

   `list-masjids` shows each masjid's length, or "Jumuah length not set (45 min estimated)". Changing it updates the calendars of everyone who uses that masjid.

What it changes in the calendar:

1. **Masjid prayers** use the masjid's iqamah, like `KMA iqamah (MAWAQIT, updated Oct 25, 2026)`. A day with no iqamah uses the calculated start time and says so. An iqamah is never made up. `+0` on a MAWAQIT page means the iqamah is at the adhan time: KMA uses it for Asr and Isha on days when its set time would come before the adhan. If a page sets `fajrFixationComparedToShuruq`, Fajr's iqamah isn't used and the worker logs it, since that setting's format isn't known.
2. **Home prayers** use the main masjid's adhan time, like `KMA adhan time (MAWAQIT)`.
3. **Jumuah**: on the coming Friday (today, if it's Friday), if you have Jumuah masjids, Dhuhr becomes `Jumuah at <masjid>`. This is where your busy times come in, not in the setup question. It uses your pick (a masjid and its 1st, 2nd, or 3rd Jumuah) if that slot fits your calendar. If it clashes, or that slot isn't on this Friday, it uses the earliest Jumuah that fits across all your Jumuah masjids. If every one clashes, it keeps your pick and says so. With no pick, it's the earliest that fits. The description says which, like `Your pick (2nd Jumuah) clashes with your calendar, so this is the earliest Jumuah that fits.`
4. **Only the coming Friday** uses MAWAQIT's Jumuah times, since a MAWAQIT page only shows this week's. Later Fridays follow your weekly grid for Dhuhr, and say `This Friday's Jumuah times aren't published yet, so this follows your weekly prayers.` They change to Jumuah once a later read covers that Friday.
5. **Jumuah length**: each masjid can have its own, set on the server (below). Without one, the block is 45 minutes and the description says the end time is estimated. Every other prayer block is 15 minutes.
6. **Freshness**: times read in the last 24 hours are fresh. Up to 7 days old, they're still used, and the description says they may be out of date. Older than that, calculated times are used.

MAWAQIT can block this at any time. After a 403, a 429, or 3 failed reads in a row, the app waits 24 hours before trying that masjid again, and keeps the last good times in the meantime.

## Drive times

Each masjid prayer gets a **Drive to <masjid>** block before it, from when to leave until you arrive, with a popup reminder when it starts. Drive times come from [OpenRouteService](https://openrouteservice.org), which has a free plan. They're typical drive times with no live traffic, and the description says so: `14 min drive (OpenRouteService, no live traffic).` The app calls `https://api.heigit.org/openrouteservice/v2/directions/driving-car`. HeiGIT shut off the old address, `api.openrouteservice.org`, on September 28, 2026.

1. Sign up at https://account.heigit.org/signup and copy your API key.
2. Put it in `.env` as `ORS_API_KEY=...` and restart: `docker compose up -d`.

With no key, there are no drive blocks, and everything else works as before. Only the rounded coordinates of your home and your masjids are sent (about 100 m), never an address. Each drive time is saved for 30 days, or until your address or masjids change.

## Nightly job

The `worker` service updates every user's calendar at 3:00 am in their own time zone. It adds the newest day, fixes any times that changed, and never touches past events. The only events it ever deletes are future drive blocks that aren't needed any more, like when a prayer moves home. Not 2:00 am, because 2:00 am doesn't exist on the spring daylight saving day.

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
| `GET /me` | Who's signed in, whether Google needs a new sign-in, whether the app can see busy times, and whether setup is done |
| `GET /settings` | Your saved setup answers |
| `POST /setup/location/suggest` | Up to 5 address suggestions from Photon for what's typed so far. Saves nothing |
| `PUT /settings/location` | Saves the suggestion the user picked (encrypted) and its time zone |
| `POST /setup/masjid/suggest` | Up to 5 masjids from Photon for what's typed so far, closest to home first, with distances. Adds addresses near home when no masjid matches. Saves nothing |
| `POST /masjids/from-suggestion` | Saves the picked suggestion as a masjid, for the main masjid or Jumuah |
| `PUT /settings/main-masjid` | Saves the main masjid, or "home". Picking a different masjid clears its short name |
| `PUT /settings/weekly` | Saves the weekly grid (7 days) |
| `PUT /settings/optional` | Saves both "how early" times, the short name, and the 2 colours. Skip sends the defaults |
| `PUT /settings/jumuah-pick` | Saves your Jumuah pick as a masjid and a slot (1st, 2nd, or 3rd), or clears it |
| `GET /jumuah/slots` | Each Jumuah slot at your Jumuah masjids (or the `masjid_id`s given, for setup), with this week's times as an example, and which one is picked. No busy times. Saves nothing |
| `PUT /settings/jumuah` | Saves the Jumuah masjids, in order (settings page only) |
| `POST /setup/finish` | Finishes setup and fills the next 14 days. The website calls it after the last question |
| `POST /calendar/sync` | Sends anything still waiting. Safe to run again |
| `POST /prayers/today` | Updates today's prayers and drive blocks from your saved settings. Safe to run again |
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

Use the same user, password, and database name as in your `.env`. You should see `681 passed`.

The tests never call the real Google, Photon, MAWAQIT, or OpenRouteService. They use fakes (`tests/fake_google.py`, `tests/fake_photon.py`, `tests/fake_mawaqit.py`, and `tests/fake_ors.py`) and fake keys, so no real settings are needed.

To run only the tests that don't need the database: `pytest -m "not database"` (`357 passed, 324 deselected`).

When you're done, stop Postgres with `docker compose down`.

### Website

```bash
cd web
npm ci
npx playwright install chromium   # once
npx playwright test
```

You should see `142 passed`: 71 tests, each on a desktop and a phone-sized screen. The tests mock the API, so the backend doesn't need to be running.
