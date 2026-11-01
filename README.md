# PrayerFit

## Demo

A demo of setting up PrayerFit and connecting it to Google Calendar.

https://github.com/user-attachments/assets/692cedce-c39d-45ee-bee5-ea631ed26695

## Try it

[prayerfit.me](https://prayerfit.me)

Sign in with Google and answer 3 quick questions. Your prayers show up in a new "Prayers" calendar in your Google Calendar.

## The problem

Is it ever annoying to keep track of how your prayer times shift over time?

1. Prayer times shift by minutes every day, and by an hour with daylight saving time.
2. Each masjid sets its own iqamah times and changes them.
3. Classes and other commitments clash with prayer times.

## How PrayerFit fixes it

Look no further. PrayerFit does this.

It syncs your daily prayers and masjid times to your Google Calendar, based on your location, and plans them around your day.

It's live at prayerfit.me and has over 40 users in Ottawa.

1. Prayer times calculated for your address, always with ISNA and standard Asr.
2. Your masjid's iqamah and Jumuah times, read from its public MAWAQIT page, or from the masjid's own announcement when MAWAQIT hasn't caught up yet. Calculated times are used when neither can be read.
3. A separate "Prayers" calendar with the next 14 days, so your other events are never touched. Every event is private.
4. A drive block before each masjid prayer, so you know when to leave.
5. Prayers that move around your classes and meetings, re-checked every 5 minutes.
6. The Jumuah slot that fits your Friday.
7. Popup reminders, a Settings page to change any answer, and a button to delete your account and everything stored.

## How it plans around your day

Your calendar events come first, and prayers work around them. The app only sees when you're busy, never what your events are.

The "normal time" is the iqamah for a masjid prayer, and the adhan for a prayer at home.

For each prayer, each day:

```
if it's a masjid prayer:
    if the drive and the iqamah are both free:
        pray at the masjid at iqamah, and stop
    else:
        it can't be at the masjid today, so plan it at home
if the normal time is free:
    pray at the normal time
else if there's a free gap of at least 10 minutes before the prayer's time ends:
    pray in the earliest one
else:
    keep it at the normal time, flagged as a clash
```

1. Each prayer's time ends at: Fajr, sunrise. Dhuhr, Asr. Asr, Maghrib. Maghrib, Isha. Isha, midnight (halfway between Maghrib and the next Fajr).
2. A prayer shrinks to fit a short gap, down to 10 minutes.
3. Jumuah uses your pick (1st, 2nd, or 3rd) if it fits, otherwise the earliest Jumuah that fits, and the 1st Jumuah, flagged, if none do.
4. All-day events, like a trip or "out of office", don't count as busy.

For example, a class from 3:00 to 4:21 covers the start of Asr, so Asr moves to 4:21, right after class.

More detail, with real examples: [Moving prayers around your calendar](docs/TECHNICAL.md#moving-prayers-around-your-calendar).

## How it's built

1. FastAPI (Python): the backend and the nightly worker.
2. Postgres, with SQLAlchemy and Alembic: the database and its migrations.
3. React and TypeScript: the website.
4. Docker Compose: runs the website, backend, worker, and database the same way on my laptop and the server.
5. Caddy: free HTTPS with Let's Encrypt.
6. An Azure Linux VM: hosts it in Canada Central.
7. GitHub Actions: runs the tests.
8. pytest and Playwright: tests for the backend and the website.

Key points:

1. I calculate prayer times in my own code, and the tests check them against 2 other libraries every day of a year. [Read more about the prayer time calculation here.](docs/TECHNICAL.md#prayer-times)
2. Masjid times come from a MAWAQIT adapter, with calculated times as the fallback when the page is stale or can't be read. Where each time came from is shown on the Settings page. [Read more about masjid times here.](docs/TECHNICAL.md#masjid-times-from-mawaqit)
3. Google sign-in is done on the server with state checks and PKCE. Google tokens are encrypted in the database, and the browser only gets an HttpOnly cookie. [Read more about sign-in here.](docs/TECHNICAL.md#google-sign-in-and-google-calendar)
4. It only asks for `calendar.app.created`, so it can manage the calendar it made and nothing else, and `calendar.freebusy`, so it sees when you're busy but never what your events are.
5. A nightly worker updates every user's calendar. Each job is saved with a stable ID like `nightly:<user id>:2026-10-24` before it runs, so a retry never runs it twice. [Read more about the nightly job here.](docs/TECHNICAL.md#nightly-job)
6. Tests: pytest and Playwright run on every push. [Read more about testing here.](docs/TECHNICAL.md#testing)

## Run it yourself

See [docs/SETUP.md](docs/SETUP.md) for running it locally, linking masjids, deploying to Azure, and running the tests.
