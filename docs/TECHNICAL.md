# PrayerFit: technical details

How each part of PrayerFit works and why it was built that way. To run it yourself, see [SETUP.md](SETUP.md). For a file by file walkthrough, see [LEARNING.md](../LEARNING.md). For the full product description, see [PrayerFit_App.md](../PrayerFit_App.md).

## Stack

1. Website: React and TypeScript, built with Vite, served by nginx
2. Backend: Python and FastAPI
3. Database: Postgres, with SQLAlchemy and Alembic for migrations
4. Nightly job: its own worker service, same code as the backend
5. Sign-in: Google, done on the server with PKCE
6. Addresses and masjids: the free Photon search, built on OpenStreetMap data
7. Masjid times: each masjid's public MAWAQIT page, with calculated times when it can't be read
8. Drive times: OpenRouteService's free plan (no live traffic)
9. Runs with Docker Compose, on an Azure VM in Canada with Caddy for HTTPS
10. Tests: pytest for the backend, Playwright for the website, both run by GitHub Actions on every push and pull request

## How it runs

Docker Compose starts 4 services:

| Service | What it does |
|---|---|
| `web` | nginx. Serves the website and passes `/api/...` and `/auth/...` to the backend. The only service the browser talks to. |
| `backend` | FastAPI. Runs the database migrations (`alembic upgrade head`) before it starts. |
| `worker` | Background jobs, checked every minute: the nightly job, reading MAWAQIT, the 5-minute busy check, and queued calendar updates. |
| `db` | Postgres. |

The website and the API share one address (`http://localhost:8000`), so the browser treats them as the same site. That's what lets the session cookie and the Origin check work.

On the server, Caddy sits in front of `web` for HTTPS (see [Hosting](#hosting)).

## Prayer times

I calculate prayer times in my own code (`backend/app/prayer_times/`), not with a library. The calendar always uses ISNA with standard Asr. There is no setting for the method.

`backend/tests/test_prayer_times_reference.py` compares my times with 2 well-known libraries, adhanpy and praytimes, every day of a year. Only the tests use them. The app never does. Daylight saving weeks and high latitudes have their own tests (`test_daylight_saving.py`, `test_high_latitude.py`).

The `/prayer-times` endpoint shows the raw calculation. Open http://localhost:8000/api/prayer-times?latitude=45.4215&longitude=-75.6972&date=2026-10-24 to get Ottawa's prayer times for that day.

| Parameter | Required | Default | Example |
|---|---|---|---|
| `latitude` | yes | | `45.4215` |
| `longitude` | yes | | `-75.6972` |
| `date` | no | today in that time zone | `2026-10-24` |
| `method` | no | `isna` | `isna`, `mwl`, `egyptian`, `karachi`, `umm_al_qura` |
| `asr_method` | no | `standard` | `standard`, `hanafi` |
| `timezone` | no | `DEFAULT_TIMEZONE` from `.env`, or `America/Toronto` | `America/Edmonton` |

Every time comes back with where it came from (`"source": "calculated"`, the method, and the Asr method).

## Google sign-in and Google Calendar

I sign in with Google and the app keeps the next 14 days of prayers in a calendar called "Prayers" that it creates in my Google account. It only asks for `openid`, `email`, `calendar.app.created`, and `calendar.freebusy`. `calendar.app.created` lets it manage calendars it made itself and nothing else. `calendar.freebusy` lets it see when I'm busy, so my prayers can fit around my day, but never what my events are. No Gmail, and it can't read my other calendars.

The app only checks my primary calendar for busy times. Checking my other calendars would need one more scope (`calendar.calendarlist.readonly`, to find them), so it doesn't. Busy times are never saved. If Google doesn't answer, the calendar update carries on, and any prayer that was already moved stays where it is (see "Moving prayers around your calendar" below).

Sign-in is done on the server (`backend/app/auth/`):

1. `/auth/google/login` sends the browser to Google with a random state and a PKCE code challenge.
2. Google sends the browser back with a one-time code and the same state, and the server checks the state.
3. The server swaps the code for tokens, proving with the PKCE code verifier that it started the sign-in.
4. Google tokens are encrypted with Fernet before they're saved (`backend/app/auth/crypto.py`), and refreshed on the server.
5. The browser only gets an HttpOnly session cookie, so page scripts can't read it.

The key (`TOKEN_ENCRYPTION_KEY`) encrypts Google tokens and home addresses. If it's lost or changed, everyone has to sign in and enter their address again.

Every event the app makes is private, so people you share your calendar with only see "busy".

In Google Calendar, the **Prayers** calendar has today and the next 13 days, like `Fajr` and `Dhuhr at KMA`. Prayers at the masjid say where. Every other prayer is just its name. Events have no description, except a prayer that was moved or clashes with your calendar (see "Moving prayers around your calendar"). Where your times come from is on the Settings page instead. Until your masjid is linked to MAWAQIT (below), masjid prayers use the calculated time.

If you move to another time zone, the Prayers calendar's time zone changes too.

## Masjid times from MAWAQIT

Masjid times come from each masjid's public page on [MAWAQIT](https://mawaqit.net). Users never see or do any of the linking. Linking a masjid by hand is a command on the server, not a website button, so a user can't link the wrong page for everyone.

### How the list works

MAWAQIT's search needs a login and it has no sitemap, so the app can't find a masjid's page by itself. I keep my own list in `backend/app/data/mawaqit_masjids.csv`, one masjid per line:

```
name,short_name,address,times_link,latitude,longitude
Kanata Muslim Association,KMA,,https://mawaqit.net/en/id/9793,45.356128,-75.9283718
Barrhaven Islamic Centre,BIC,"3971 Greenbank Road, Ottawa",https://mawaqit.net/en/id/17559,45.2364361,-75.7255711
Masjid ar-Rahmah,AMA,"1216 Hunt Club Rd., Ottawa",https://www.mymasjid.ca/prayer/,45.3517835,-75.6473151
```

It has 24 masjids around Ottawa: 23 on MAWAQIT, and Masjid ar-Rahmah (AMA), read from its own website (see "Masjid ar-Rahmah from mymasjid.ca" below). `short_name` and `address` are optional. Setup's search finds a masjid by its short name too, and shows the address under its name. A MAWAQIT link is either a share link (`https://mawaqit.net/en/id/9793`, from MAWAQIT's Share button) or a page link (`https://mawaqit.net/en/cio-gatineau`). The app saves `id/9793` or `cio-gatineau` and reads the times from that link. A share link answers with the masjid's page straight away.

The backend and the worker load the file every time they start. Loading it again never adds a copy. If I fix a name or a location in the file, the saved one changes too.

### Masjid search in setup

Setup searches my list first, then Photon (`backend/app/masjid_search.py`). I built it this way because a user typed "Barrhaven Islamic Centre" and it didn't show up. Photon only finds what OpenStreetMap has, under the name and tags it has there, and it doesn't forgive typos well.

1. Every word typed has to match a word of the name or the short name. A word matches if it's the same, the start of one ("barr" finds "barrhaven"), or close with a small typo ("barhaven" finds "barrhaven"). Words like "masjid", "mosque", and "centre" are skipped. So "barrhaven", "BIC", and "barhaven islamic" all find BIC.
2. List masjids come first, best match first, then nearest, whatever the distance, since I picked each one by hand.
3. Photon's results come after. Any that's the same masjid as a list one already shown is dropped: within 100 m, within 200 m with a close name, or the same name within 2 km.
4. At most 5 in total. If Photon is down, the list results still show.
5. Picking a list masjid saves it with `source = "list"` and links it to its MAWAQIT page straight away. Picking it again reuses the same row. If someone already picked the same masjid from OpenStreetMap and it's linked to that list entry, that row is reused, so /stats counts it once.

### Matching a masjid from OpenStreetMap

When a user picks a masjid from Photon in setup, the app matches it against the list straight away:

1. Within 100 m: a match, even if the names are different. Map names are often spelled differently, like "MAC QIC".
2. From 100 m to 200 m: a match only if the names closely match, ignoring words like masjid, mosque, association, centre, and Ottawa.
3. It links only if exactly 1 listed masjid matches. Otherwise it doesn't link, and the masjid shows on /stats with a "No MAWAQIT times" tag.

Then it reads the masjid's page right away, so the Jumuah question in setup already has the masjid's real Jumuah times. If MAWAQIT is down, picking the masjid still works, and calculated times are used until the worker reads it.

When the list changes, the masjids users already picked are matched again. An automatic link never replaces one I made with `link-mawaqit`, and a masjid I unlinked with `unlink-mawaqit` is never linked again automatically.

Masjids that aren't on MAWAQIT get calculated prayer start times only, with no iqamah, for now.

### BIC

Barrhaven Islamic Centre (BIC) is the 2nd masjid with a saved MAWAQIT page in the tests, after KMA. `backend/tests/fixtures/mawaqit/bic_page.html` is its real page (https://mawaqit.net/en/id/17559), saved on November 1, 2026. Tests only read the saved copy.

1. It publishes 2 Jumuah times, 1:00 pm and 2:30 pm. Its 3rd Jumuah is empty, so the parser gives 2 slots, numbered 1 and 2.
2. `test_mawaqit_bic.py` checks Nov 1's adhan and iqamah, the clock change, both Jumuah times, and that every day of the year passes the checks.

### Masjid ar-Rahmah from mymasjid.ca

Masjid ar-Rahmah (AMA, 1216 Hunt Club Rd., Ottawa) isn't on MAWAQIT. Its prayer page, https://www.mymasjid.ca/prayer/, shows an "Iqaama Timetable" in an iframe. The iframe is a small HTML table from `https://app.mymasjid.ca/protected/public/timetable`, with an Adhān and an Iqāmah column for each prayer and 2 Jumuah rows. Its own adapter, `backend/app/masjid_times/mymasjid.py`, reads it, separate from the MAWAQIT adapter, so one breaking never breaks the other.

1. **Today only**: the table has no date, and no way to ask for another day. Each read is saved as the masjid's local date at that moment. Days that haven't been read use calculated times, never a copy of another day.
2. **Names**: "Zuhr" on the page is Dhuhr.
3. **Missing iqamah**: an empty Iqāmah cell stays empty, the calculated start time is used, and the worker logs it. An iqamah is never made up.
4. **Jumuah**: the 2 Jumuah rows only have a time in the Adhān column. They're the Jumuah start times (12:00 pm and 1:30 pm when it was saved), with no iqamah claimed. They're saved on the masjid's source for the coming Friday (`masjid_sources.upcoming_jumuah`), since Friday has no row until Friday comes. The Jumuah question and the calendar use them like MAWAQIT's.
5. **Checks**: the same per-day checks as MAWAQIT (`validate.py`). It's the only day on the page, so a failed check rejects that read and says which prayer. A bad Jumuah time only skips Jumuah, and the last good Jumuah times stay.
6. **Freshness**: the same rules as MAWAQIT, measured from the last good read. After 24 hours Settings shows `AMA's times couldn't be confirmed since Nov 3, 2026. Your calendar is using calculated times for the days mymasjid.ca couldn't be read.` A day that was read keeps its times for up to 7 days.
7. **When it's read**: the page has no date, so it's only read from 12:15 am to 6:45 pm Toronto time. That's safe whether the page switches days at midnight in Toronto or at midnight UTC (7 pm, or 8 pm in summer). The first read is at 12:15 am, hours before Fajr, so that day's Fajr iqamah is in the calendar in time. Until a read works it's tried every hour. After 3 failures it waits for the 12:00 pm read, then for the next day's 12:15 am read. A 403 or 429 waits 24 hours. From 12:00 pm it's read once more. A normal day is 2 reads: 12:15 am and 12:00 pm.
8. **Where it's from**: name and address from the masjid's contact page. The location is the centre of the building on OpenStreetMap (way 483089921, 45.3517835, -75.6473151), which is within about 10 m of the pin on the masjid's own map.
9. **Tests**: `test_mymasjid.py` reads a saved copy of the table from November 3, 2026 (`backend/tests/fixtures/mymasjid/`). `test_mymasjid_calendar.py` follows it to the calendar. Tests never call the real site.

### What it changes in the calendar

1. **Masjid prayers** use the masjid's iqamah. Settings shows where it came from, like `Times from MAWAQIT, updated Oct 25, 2026`. A day with no iqamah uses the calculated start time. An iqamah is never made up. `+0` on a MAWAQIT page means the iqamah is at the adhan time: KMA uses it for Asr and Isha on days when its set time would come before the adhan. If a page sets `fajrFixationComparedToShuruq`, Fajr's iqamah isn't used and the worker logs it, since that setting's format isn't known.
2. **Location**: masjid prayer blocks (Jumuah too) have the masjid as their Google Calendar location, like `Kanata Muslim Association, 351 Sandhill Road, Ottawa`: its saved name and public address, with no postal code. Home, moved, and clash prayers have none, and the user's home address is never in an event. A masjid picked by typing an address gets none either. Drive blocks have none.
3. **Home prayers** use the main masjid's adhan time.
4. **Jumuah**: Jumuah is always at your main masjid. On the coming Friday (today, if it's Friday), Dhuhr becomes `Jumuah at <masjid>`. This is where your busy times come in, not in the setup question. It uses your pick (its 1st, 2nd, or 3rd Jumuah) if that slot fits your calendar, with no description. If it clashes, or that slot isn't on this Friday, it uses the earliest Jumuah that fits, and the description says `Your pick (1st Jumuah) clashes with your calendar, so this is the earliest Jumuah that fits.` (or `isn't on this Friday`). If every one clashes, it uses the 1st Jumuah, and the description says `Every Jumuah clashes with your calendar, so this is the 1st Jumuah.` If you pray at home, or your masjid has no Jumuah times, there's no Jumuah and Friday follows your weekly prayers.
5. **Only the coming Friday** uses MAWAQIT's Jumuah times, since a MAWAQIT page only shows this week's. Later Fridays follow your weekly grid for Dhuhr, and say `This Friday's Jumuah times aren't published yet, so this follows your weekly prayers.` They change to Jumuah once a later read covers that Friday.
6. **Jumuah length**: each masjid can have its own, set on the server ([SETUP.md](SETUP.md#linking-a-masjid-by-hand)). Without one, the block is 45 minutes. The other prayer blocks are Fajr 10 minutes, Dhuhr 15, Asr 10, Maghrib 10, and Isha 15.
7. **Freshness**: each read saves a full 30-day calendar from MAWAQIT, so if MAWAQIT can't be read, the last times read are kept for up to 7 days.
   a) Under 24 hours since the last good read: the times are used.
   b) 24 hours to 7 days: the times are still used, and Settings shows a notice at the top: `KMA's times couldn't be confirmed since Oct 24, 2026. Your calendar is still using the last times read from MAWAQIT, and switches to calculated times on Oct 31, 2026 if they still can't be read.`
   c) Over 7 days: your calendar uses calculated times until a read works again, and the notice says `Your calendar is using calculated times until they're back.` A calculated start is never later than the iqamah, so you're early, never late.

MAWAQIT can block this at any time. After a 403, a 429, or 3 failed reads in a row, the app waits 24 hours before trying that masjid again, and keeps the last good times in the meantime.

### Announced times

Sometimes a masjid announces new times before its MAWAQIT page shows them. KMA announced new iqamah and Jumuah times for when the clocks fell back on November 1, 2026, but its page still showed Fajr at adhan + 15 (the announcement says adhan + 30 from November 1), Isha at 6:40 pm, and Jumuah at 12:45, 2:00, and 2:50. The announcement is the masjid's own published source, so the app can use it, as long as it's written down where it gets reviewed.

1. **Where they're kept**: one JSON file per masjid in `backend/app/masjid_times/announced/`, like `kma.json`. Every change goes through a PR, the same as code. Steps to add one are in [SETUP.md](SETUP.md#announced-times).
2. **Each entry** has a start date, an end date (both included), and iqamah times, Jumuah times, or both. An iqamah is a clock time (`"12:30"`) or an offset (`"adhan + 30"`, `"sunset + 5"`). Jumuah is up to 3 clock times, used on each Friday in the range.
3. **Which masjid**: a file names the masjid's MAWAQIT IDs (`id/9793`, `kma-masjid-ottawa`), not a database ID, since that's different on my laptop and on the server. `load_masjid_times` attaches the file to the masjid linked to either ID.
4. **What wins**: inside an entry's range, its iqamah and Jumuah times win over MAWAQIT. A prayer an entry leaves out keeps MAWAQIT's iqamah. Outside every range, nothing changes. Announced times are used whatever MAWAQIT's freshness, since they come from the repo, not a website.
5. **Only iqamah and Jumuah**: adhan times for home prayers, and each prayer's window for moving, still come from MAWAQIT or the calculation.
6. **Offsets**: "adhan + 30" counts from the masjid's adhan on MAWAQIT when its times are usable, otherwise from the calculated adhan. "Sunset" is the Maghrib adhan, since Maghrib starts at sunset. The minutes are added in real time (UTC), so a clock change can't stretch or shrink them.
7. **Sources**: each event's source says where it came from, like `KMA iqamah (KMA announcement)`, `KMA iqamah (KMA announcement: 30 minutes after KMA's adhan time from MAWAQIT)`, or `KMA Jumuah (KMA announcement)`. Settings adds `Iqamah and Jumuah times from the KMA announcement are used from Nov 1 to Nov 30, 2026` to the masjid's line.
8. **Later Fridays**: MAWAQIT only has this week's Jumuah, so later Fridays usually follow the weekly grid. A Friday with announced Jumuah times gets Jumuah, even if it isn't the coming one.
9. **Everything else is the same**: the drive block, the leave time, the Jumuah pick, and moving prayers around busy times all use the announced time as the normal time, with no other changes.
10. **When a file is wrong**: a bad time, a missing key, an end before a start, or 2 entries giving the same prayer on the same date refuses the whole file, since a half-read file could give a wrong time. It's logged (`Announced times in kma.json weren't used: ...`) and that masjid falls back to MAWAQIT, then calculated times, as normal. One bad file never affects another masjid.

The code is in its own small module, `backend/app/masjid_times/announced.py`, separate from the MAWAQIT adapter, so one breaking never breaks the other. The tests are in `test_announced.py`.

## Drive times

Each masjid prayer gets a **Drive to <masjid>** block before it, from when to leave until you arrive. It gets a popup 5 minutes before you leave, which you can change or turn off in "Notifications" ([SETUP.md](SETUP.md#5-notifications)). Drive times come from [OpenRouteService](https://openrouteservice.org), which has a free plan. They're typical drive times with no live traffic. The app calls `https://api.heigit.org/openrouteservice/v2/directions/driving-car`. HeiGIT shut off the old address, `api.openrouteservice.org`, on September 28, 2026.

With no key, there are no drive blocks, and everything else works as before. Only the rounded coordinates of your home and your masjids are sent (about 100 m), never an address. Each drive time is saved for 30 days, or until your address or masjids change.

## Moving prayers around your calendar

Anything in my primary Google Calendar comes first, and each prayer works around it. The app only sees when I'm busy, never what the event is.

1. **At the masjid**: a masjid prayer stays at the masjid only if the drive, the "how early" minutes, and the prayer block are all free. Otherwise it's prayed at home that day, and its drive block is deleted.
2. **At the normal time** if that's free. The normal time is the iqamah for a masjid prayer that can't go to the masjid, and the adhan for every other prayer.
3. **Otherwise, the earliest free time** of at least 10 minutes, from the start of the prayer's time to its end. A gap shorter than the prayer's usual length shrinks it to fit, down to 10 minutes. For example, a 12-minute gap fits Isha as a 12-minute block. The description says how far after the prayer's start time (the adhan) it went, like `Moved because of an event in your calendar (42 minutes after Dhuhr's start time).` Over an hour it says `1 hour 12 minutes`, and right at the adhan it says `(at Dhuhr's start time)`.
4. **No free time at all**: it stays at the normal time, titled `Asr (clash)`, and the description says `Your event covers all of Asr's time today, so figure out a way to fit it in. Busy from 3:00 to 6:30 pm.` The "Busy from" part lists each busy time inside that prayer's time, joined with "and". A time on another day gets its date, like `Oct 26, 11:00 pm to 7:00 am`.

Those are the only descriptions. The app only knows when I'm busy, never what my events are, so a description never names the event. The "Busy from" part is times only.

**All-day events don't count.** Free/busy only sends start and end times, so the app can't tell an all-day event from a long timed one. `busy_times.py` leaves out any busy block of 23 hours or more (`ALL_DAY`).
1. Why: an all-day event, like a trip or "out of office", marks the day. It almost never means there's no time to pray. Counting it made every prayer that day a clash.
2. Why 23 hours and not 24: the spring daylight saving day is only 23 hours long, so its all-day event is too.
3. Why a length and not "midnight to midnight": a Google Calendar set to another time zone puts an all-day event at 8 pm to 8 pm in Ottawa.
4. The catch: free/busy joins overlapping blocks, so a call during an all-day event is left out too. Splitting them would need a wider scope than `calendar.freebusy`.

Events marked "Free" don't block time in free/busy, so they never reach the app. Declined events should be left out the same way, but I still need to check that against a test calendar.

**When Google fails** (a 500, errors for the primary calendar, an answer that can't be read, or an answer with no primary calendar at all), the busy times are "unknown", never "free all day":
1. Nothing new gets flagged as a clash or moved.
2. Prayers that were already moved or flagged stay as they are, so nothing flips back and forth.
3. The 5-minute check writes nothing to Google and tries again next time.

Each prayer's time ends at: Fajr, sunrise. Dhuhr, Asr. Asr, Maghrib. Maghrib, Isha. Isha, midnight, which is halfway between Maghrib and the next day's Fajr, so it never suggests 2 am.

Examples, with Isha at KMA (adhan 7:23 pm, iqamah 7:40 pm, a 10 minute drive):
1. A class until 7:35 pm: `Isha` at 7:40 pm, at home.
2. A class from 7:00 to 8:30 pm: `Isha` at 8:30 pm.
3. A meeting from 7:45 to 9:00 pm: `Isha` at 7:23 pm, before the meeting.

**Every 5 minutes**, the worker checks each user's busy times for today and tomorrow, and sends only the events that changed. So a new event moves the right prayer within 5 minutes, and deleting it puts the prayer back within 5 minutes. The nightly job still covers all 14 days. Each check is saved with an ID like `busy:<user id>:2026-10-26T19:45` before it runs, so it runs once per 5 minutes even with 2 workers.

It stays inside Google Calendar's free quota. Google doesn't charge under 1,000,000 requests a day per project, and allows 10,000 a minute per project and 600 a minute per user. For 1,000 users:
1. Busy checks: 288 a day each (every 5 minutes), so 288,000 a day. A quiet check is 1 free/busy call.
2. Everything else (the nightly job, moved prayers, settings changes): roughly 20,000 a day.
3. Total: about 310,000 a day, about 31% of the free 1,000,000.
4. Per minute: at most about 200 checks spread over each 5 minutes, well under 10,000. Each user makes about 1 call every 5 minutes, far under 600 a minute.
5. The free 1,000,000 would run out at around 3,200 users at this rate.

Things that never happen:
1. Events that already started are never moved. That includes a masjid prayer once its drive has started.
2. A moved prayer is never put in the past.
3. The Prayers calendar never counts as busy.
4. If free/busy doesn't answer, nothing that was moved is put back, and nothing new is flagged. The 5-minute check changes nothing at all and tries again next time.
5. Users who didn't allow free/busy get no moving. Everything works as before for them.

## Nightly job

The `worker` service updates every user's calendar at 3:00 am in their own time zone. It adds the newest day, fixes any times that changed, and never touches past events. The only events it ever deletes are future drive blocks that aren't needed any more, like when a prayer moves home. Not 2:00 am, because 2:00 am doesn't exist on the spring daylight saving day.

Each job is saved with an ID like `nightly:<user id>:2026-10-24` before it runs, so a retry or a second worker can't run it twice. If the worker was off at 3:00 am, it catches up when it starts. If one user's Google sign-in expired, their job is marked `needs_sign_in` and everyone else still gets updated.

## Usage stats

Counts only. Never emails, names, addresses, or anything else about a user.

1. **Total users**: everyone who ever signed in.
2. **Masjids**: each masjid at least 1 user picked as their main masjid, most users first. A masjid picked by its address shows as "(picked by address)", never the address. "(no MAWAQIT times)" means it isn't linked, so it's one to add to the MAWAQIT list.

The private /stats page has 2 cards:

1. **Total users over time**, styled like YouTube Studio's views graph, in PrayerFit's own colours and font:
   a) A dropdown at the top right: 1 day, 2 days, 3 days, 5 days, 7 days (the default), 30 days, or All time.
   b) One big sentence with today's total, like "PrayerFit has 41 users".
   c) One thin line with straight segments between points, and no dot on each point. A smoothed curve could draw a dip that never happened.
   d) 1 to 3 days have one point per hour. 5 days and up have one point per day. Each point is the total users at the end of that hour or day, or right now for the current one.
   e) Light grid lines with labels on the right: 4 or 5 whole numbers from 0, up to a round number just above the highest total, like 0, 20, 40, 60. With few users it's 0, 1, 2, 3. From 1,000 on they say "1K", "1.5K".
   f) 5 to 7 evenly spaced labels along the bottom: round hours (like every 4 hours) for 1 to 3 days, with the date at midnight, and dates for longer ranges.
   g) Point at the graph (or tap it on a phone) and a dot appears on the line at the closest point, with a card above it: the date, the hour when it's hourly, and the total in large bold text. Moving off the graph or tapping elsewhere hides it. With the keyboard, tab to the graph and use the arrow keys, Home, and End.
   h) All times are Toronto time.
   e) The line goes down when someone deletes their account. It's built from `user_count_changes`: how many people signed up and how many deleted their account in each hour. That table has no user ID, no email, and nothing else that leads back to a person.
2. **Masajid**: each masjid and how many users picked it, with a small "No MAWAQIT times" tag on masjids that aren't linked.

Anyone else, signed in or not, gets "Page not found". Nothing links to it. With `ADMIN_EMAIL` empty, nobody can open it.

## Look

Light only: white, black, and green, on a light green page. It looks the same whatever your device's dark mode setting is. The grey-green text for labels and hints is at least 5.6:1 against the light green, so it's easy to read.

## Endpoints

Through nginx, every endpoint below is under `/api` (like `/api/me`), except the `/auth/...` ones.

| Endpoint | What it does |
|---|---|
| `GET /auth/google/login` | Starts sign-in (open it in the browser) |
| `GET /auth/google/callback` | Google sends you back here, then to the website |
| `POST /auth/logout` | Signs out |
| `DELETE /account` | Deletes the account: the Prayers calendar, the app's Google access, and everything stored. Answers `{"google_cleaned": false}` when Google couldn't be reached |
| `GET /me` | Who's signed in, whether Google needs a new sign-in, whether the app can see busy times, and whether setup is done |
| `GET /settings` | Your saved setup answers |
| `POST /setup/location/suggest` | Up to 5 address suggestions from Photon for what's typed so far. Saves nothing |
| `PUT /settings/location` | Saves the suggestion the user picked (encrypted) and its time zone |
| `POST /setup/masjid/suggest` | Up to 5 masjids for what's typed so far: matches from my MAWAQIT list first, then Photon's, closest to home first, with distances. Adds addresses near home when no masjid matches. Saves nothing |
| `POST /masjids/from-suggestion` | Saves the picked suggestion as a masjid, for the main masjid or Jumuah |
| `PUT /settings/main-masjid` | Saves the main masjid, or "home". Picking a different masjid clears its short name |
| `PUT /settings/weekly` | Saves the weekly grid (7 days) |
| `PUT /settings/optional` | Saves both "how early" times, the short name, the 2 colours, and the 2 notifications. Skip sends the defaults. Every minutes value must be a whole number from 0 to 60, or it answers 422 with "Enter a whole number of minutes from 0 to 60." |
| `PUT /settings/jumuah-pick` | Saves your Jumuah pick as your main masjid and a slot (1st, 2nd, or 3rd), or clears it |
| `POST /jumuah/slots` | Each Jumuah slot at your main masjid (or the `masjid_id` given, for setup), with this week's times as an example, its leave time, which one is picked, and the masjid's name if it has no Jumuah times yet. No busy times. A POST because it may ask OpenRouteService for a drive time |
| `POST /calendar/preview` | This week's prayers and drive blocks at their real times, for the "Adding your prayers" page. Nothing goes to Google |
| `GET /admin/stats` | Each masjid's users, with whether it has MAWAQIT times. 404 for everyone but `ADMIN_EMAIL` |
| `GET /admin/stats/users?range=7d` | Total users over time for the graph. `range` is `1d`, `2d`, `3d` (one point per hour), `5d`, `7d`, `30d`, or `all` (one point per day). 404 for everyone but `ADMIN_EMAIL` |
| `POST /setup/finish` | Finishes setup and fills the next 14 days. The website calls it after the last question |
| `POST /calendar/sync` | Sends anything still waiting. Safe to run again |
| `POST /prayers/today` | Updates today's prayers and drive blocks from your saved settings. Safe to run again |
| `GET /prayers/today/events` | Your saved events for today |

POST and PUT requests need an `Origin` header matching `APP_ORIGIN`. Browsers send it on their own. With curl, add `-H "Origin: http://localhost:8000"`.

## Hosting

PrayerFit runs on one small Linux VM on Azure, with the same Docker Compose setup as my laptop plus Caddy in front for HTTPS. It's at https://prayerfit.canadacentral.cloudapp.azure.com until I switch to prayerfit.me.

### Why a VM

I compared 3 ways to host it on my Azure for Students credit ($100 for 12 months, no credit card):

| | Linux VM + Docker Compose | Azure Container Apps | App Service |
|---|---|---|---|
| Cost | VM (B2pts v2, Arm64) and a 64 GB disk are in the free tier. Only the static public IP uses credit, about $3 to $4 a month | Free request grant, but the always-on worker uses vCPU time all day, and Postgres needs Azure Database for PostgreSQL (free for 12 months, then paid) | Free F1 has no always-on and no background worker. B1 is about $13 a month, which runs past $100 |
| Effort | Lowest. Same compose file as my laptop | New config for every service, plus a managed database | Same Postgres problem, and the worker needs a second app |
| Skills | Linux (SSH, firewall, cron, swap, updates) and Cloud (VM, network rules, public IP, DNS, budgets) | Cloud only | Cloud only |

The VM covers both skills from my job postings and costs about $45 of the $100 over 12 months.

### What runs on the server

| File | What it does |
|---|---|
| `docker-compose.prod.yml` | Added on top of `docker-compose.yml`. Adds Caddy, restarts every service after a crash or reboot, limits log size, and takes away the public ports of `db` and `web` |
| `deploy/Caddyfile` | Caddy gets a free Let's Encrypt certificate for `SITE_ADDRESS`, renews it, sends http to https, and moves any other name to `APP_ORIGIN` |
| `deploy/production.env.example` | The server's `.env`, with placeholders only. The real `.env` only ever lives on the server |
| `deploy/server-setup.sh` | Run once: Docker, a 2 GB swap file, Toronto time, the ufw firewall, SSH keys only, automatic security updates, and the daily backup |
| `deploy/backup.sh` | Saves the database to `~/prayerfit-backups/` every day at 3:30 am and keeps 14 days |
| `deploy/update.sh` | After I merge a PR: pulls `main`, rebuilds, restarts, and checks `/api/health` |

Only Caddy is reachable from the internet, on ports 80 and 443. Postgres has no public port.

The VM is Arm64, not x86 like my laptop. Every image in the compose files (Postgres, Python, Node, nginx, and Caddy) has an Arm64 version, and Docker picks it by itself, so nothing changes in the files. The one difference: `timezonefinder` has no ready-made Arm64 package, so on the server pip builds it from source. There's no C compiler in the `python:3.13-slim` image, so it uses its pure-Python version instead of its C part. It gives the same time zones, a little slower, and it's only used when someone saves an address.

## Testing

The tests never call the real Google, Photon, MAWAQIT, or OpenRouteService. They use fakes (`tests/fake_google.py`, `tests/fake_photon.py`, `tests/fake_mawaqit.py`, and `tests/fake_ors.py`) and fake keys, so no real settings are needed.

GitHub Actions runs both (`.github/workflows/tests.yml`) on every push and every pull request, with a throwaway Postgres for the backend tests. No real keys are used anywhere. To run them yourself, see [Run the tests](SETUP.md#run-the-tests).
