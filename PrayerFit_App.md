# PrayerFit

A website that keeps your prayer times up to date in your Google Calendar.

The Prophet ﷺ was asked which deed is most beloved to Allah ﷻ, and he said praying on time (Sahih al-Bukhari 527).

---

## Prayers it covers

1. The five daily prayers
2. Jumuah
3. Duha
4. Tahajjud
5. Eid prayer
6. Taraweeh
7. Janazah, when your masjid holds one

---

## How it works

It's a website.

1. **Sign up:** sign in with your Google account and give it permission to add events to your Google Calendar.
2. **Answer a few questions**  
   a) Your address.  
   b) The masjid you usually go to.  
   c) Which prayers you usually pray at the masjid.  
   d) Which masjids you can go to for Jumuah.
3. **It runs in the background:** it fills your Google Calendar with your prayers and keeps them up to date.
4. **Edit anytime:** you can see and change your prayers on the website, like moving one or switching a day to praying at home, and the change shows up in Google Calendar. If you edit a prayer directly in Google Calendar, the website keeps your change.

---

## Problems it solves

1. **Prayer times change every day:** they shift by minutes each day and by an hour with daylight saving time, so keeping them in your calendar means constantly editing them.
2. **Masjid times are different:** a masjid's iqamah time isn't the same as the regular prayer time, each masjid sets its own, and masjids change them.
3. **Getting to the masjid on time is guesswork:** the drive takes longer in winter than in summer, and a traffic jam or car crash can change it again. It checks the drive time at that moment and tells you when to leave, for example leaving at 5:45 for a 6:00 am Fajr.

---

## Features

1. **Praying at home**  
   a) It places Duha at its best time, once the sun is high, not right after sunrise. The Prophet ﷺ said the prayer of the penitent is when young camels feel the heat of the sun (Sahih Muslim 748).

2. **Praying at the masjid**  
   a) Your calendar uses your masjid's iqamah times and updates them when the masjid changes them. For example: KMA moves Isha from 8:00 pm to 8:15 pm.  
   b) Jumuah: it picks the Jumuah time that fits your Friday schedule from the masjids you can go to, like Stittsville or Jamia Omar if you live in the Stittsville area.

3. **Moving prayers around your commitments**  
   a) When another commitment clashes with a prayer, like picking up your brother from school, it moves the prayer to the closest time that works, at home or at the next jamaah you can catch, before the prayer's time ends.  
   b) For commitments that repeat, you set them once, and it plans around them every week.

4. **Notifications**  
   a) It notifies you when a masjid changes a time or when one of your prayers gets moved, so changes don't happen silently in your calendar.

---

## Stretch goals

1. **University jama'ah hub (big stretch goal)**  
   a) Students upload their class schedules, including where each class is.  
   b) For each prayer, it picks the closer prayer area, like Paterson Hall or Nideyinàn at Carleton, and finds other students who are free at the same time near the same area.  
   c) If no jama'ah fits, you can post that you're planning to pray, like "Hakeem is praying Dhuhr at Paterson at 1:15," and students who are free nearby get a notification to join.  
   d) It matches students with similar schedules so they can go to the masjid together, like for Jumuah.  
   e) Others only see when you're free and where you'll pray, never your full schedule.

2. **AI timetable reading**  
   a) Many masjids only post their times on a poster, a photo, or a website.  
   b) An AI reads the timetable when it changes and turns it into times, once per masjid, not per user, so a free AI tier should cover the cost.  
   c) A masjid admin confirms every time before anyone's calendar changes.

---

## Skills it builds

1. **From your job postings**  
   a) Python backend services: the server that saves your settings, works out prayer times, and updates Google Calendar.  
   b) Cloud platform: hosting the website and server. Use Azure with student credit so you can name Azure on your resume.  
   c) Real database (Postgres): storing users, settings, masjids, and each prayer event.  
   d) Docker: packaging the server and database so they run the same on your laptop and in the cloud.  
   e) Data structures and algorithms: fitting prayers around commitments within each prayer's time, and picking the best Jumuah slot.  
   f) Test tools (pytest): testing prayer time calculations and scheduling, where a mistake means a missed prayer.  
   g) Linux: running the server in the cloud.  
   h) Agentic AI: covered only if you build the AI timetable reading stretch goal.

2. **Not in your postings, but still a plus**  
   a) OAuth: letting users sign in with Google and safely give access to only their calendar.  
   b) Third-party APIs: working within Google Calendar's rules and usage limits.  
   c) Two-way sync: keeping website edits and Google Calendar edits matched without one overwriting the other.  
   d) Scheduled background jobs: the nightly update that runs with no one watching.  
   e) Time zones and daylight saving time, which are famously easy to get wrong.  
   f) Maps APIs: drive times and leave times.  
   g) Notifications: email or browser alerts when something changes.  
   h) React: the website dashboard, which is your strongest skill.  
   i) Privacy and security: protecting people's addresses and calendar access.  
   j) Real users: building for the Carleton MSA and KMA and improving from their feedback.
