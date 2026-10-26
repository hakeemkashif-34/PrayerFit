// The new tab that opens on Finish (see finishTab.ts). It shows a message
// until the setup tab says the first calendar update is done, then opens
// Google Calendar here.
//
// While it waits, a week calendar fills in: times down the side, 7 days
// across, and each day's prayers from Fajr to Isha at their real times. A
// drive block slides in just before each masjid prayer, in the drive
// colour. One block goes in about every second, and a caption names it,
// like "Adding Thursday's Asr". Then it starts again.
//
// The real times come from POST /api/calendar/preview, which plans this
// week without saving or sending anything. Setup may still be saving its
// last answers when this tab opens, so it asks a few times. If it still
// can't get them, it shows a typical week instead.
// Users who turn off motion get a simple spinner.

import { useEffect, useState, type CSSProperties } from "react";
import { api } from "./api";
import { GOOGLE_CALENDAR_PREFIX } from "./googleCalendar";
import { GOOGLE_COLOURS, hourText, minutesIntoDay, WEEKDAYS } from "./labels";
import type { Preview, PreviewEvent } from "./types";

const BLOCK_MS = 1000;
// After the last block, the full week stays up this many blocks' worth before starting again.
const HOLD_BLOCKS = 3;
const ASK_TIMES = 6;
const ASK_EVERY_MS = 1200;

// The app's green, used when no Google colour was picked.
const GREEN = "#17663f";
const DRIVE_GREEN = "#0f4a2d";

const hex = (id: string | null) => GOOGLE_COLOURS.find((c) => c.id === id)?.hex ?? null;

// Only one of Google's 11 colour IDs counts. Anything else uses the app's green.
function colourFromUrl(): string | null {
  return hex(new URLSearchParams(window.location.search).get("colour"));
}

const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// "2026-10-26" -> 0 for Monday, the same numbering as the rest of the app.
function weekday(localDate: string): number {
  const [y, m, d] = localDate.split("-").map(Number);
  return (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;
}

// A typical week, when the real times can't be read: no drives, round times.
function typicalWeek(): Preview {
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const times: [PreviewEvent["prayer"], string, number, number][] = [
    ["fajr", "Fajr", 6, 0], ["dhuhr", "Dhuhr", 13, 0], ["asr", "Asr", 15, 45],
    ["maghrib", "Maghrib", 18, 0], ["isha", "Isha", 19, 30],
  ];
  const events: PreviewEvent[] = [];
  const today = new Date();
  for (let n = 0; n < 7; n++) {
    const day = new Date(today.getFullYear(), today.getMonth(), today.getDate() + n);
    const localDate = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
    for (const [prayer, title, hour, minute] of times) {
      const start = new Date(day.getFullYear(), day.getMonth(), day.getDate(), hour, minute);
      const end = new Date(start.getTime() + 15 * 60_000);
      events.push({ local_date: localDate, prayer, kind: "prayer", title, starts_at: start.toISOString(), ends_at: end.toISOString() });
    }
  }
  return { time_zone: zone, prayer_color_id: null, drive_color_id: null, events };
}

// Where a block ends on its day's column. Isha can end just after midnight, so that stops at midnight.
function endOf(event: PreviewEvent, zone: string): number {
  const start = minutesIntoDay(event.starts_at, zone);
  const end = minutesIntoDay(event.ends_at, zone);
  return end > start ? end : 24 * 60;
}

// "Adding Thursday's Asr", or "Adding Thursday's drive to KMA".
function caption(event: PreviewEvent): string {
  const day = WEEKDAYS[weekday(event.local_date)];
  const what = event.kind === "drive" ? event.title.replace(/^Drive/, "drive") : event.title;
  return `Adding ${day}'s ${what}`;
}

function WeekFilling({ preview }: { preview: Preview }) {
  const zone = preview.time_zone;
  const days = [...new Set(preview.events.map((e) => e.local_date))].sort();
  // Day by day, and within a day in time order, so each drive comes just before its prayer.
  const order = [...preview.events].sort(
    (a, b) => a.local_date.localeCompare(b.local_date) || a.starts_at.localeCompare(b.starts_at),
  );
  const [shown, setShown] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(
      () => setShown((n) => (n >= order.length + HOLD_BLOCKS ? 0 : n + 1)),
      BLOCK_MS,
    );
    return () => window.clearInterval(timer);
  }, [order.length]);

  // Times down the side: from the hour before the first block to the hour after the last.
  const starts = order.map((e) => minutesIntoDay(e.starts_at, zone));
  const ends = order.map((e) => endOf(e, zone));
  const top = Math.floor(Math.min(...starts) / 60) * 60;
  const bottom = Math.min(24 * 60, Math.ceil(Math.max(...ends) / 60) * 60);
  const span = bottom - top;
  const pct = (minutes: number) => `${((minutes - top) / span) * 100}%`;
  const hours: number[] = [];
  for (let m = top; m <= bottom; m += 60) hours.push(m);

  const prayerColour = hex(preview.prayer_color_id) ?? colourFromUrl() ?? GREEN;
  const driveColour = hex(preview.drive_color_id) ?? DRIVE_GREEN;
  const current = shown > 0 && shown <= order.length ? order[shown - 1] : null;
  const style = { "--prayer": prayerColour, "--drive": driveColour } as CSSProperties;

  return (
    <div className="week-filling" style={style}>
      <p className="adding-caption" aria-hidden="true">
        {current ? caption(current) : shown === 0 ? "Getting started…" : "Your week is in"}
      </p>
      <div className="week" aria-hidden="true">
        <div className="week-head">
          <span />
          {days.map((day) => (
            <span key={day} className={current?.local_date === day ? "week-day now" : "week-day"}>
              {WEEKDAYS[weekday(day)].slice(0, 3)}
              <small>{Number(day.slice(8))}</small>
            </span>
          ))}
        </div>
        <div className="week-body">
          {hours.map((m) => (
            <div key={m} className="week-hour" style={{ top: pct(m) }}>
              <span>{hourText(m)}</span>
            </div>
          ))}
          {days.map((day, column) => (
            <div key={day} className="week-column" style={{ gridColumn: column + 2 }}>
              {order.slice(0, shown).filter((e) => e.local_date === day).map((e) => {
                const start = minutesIntoDay(e.starts_at, zone);
                const end = endOf(e, zone);
                return (
                  <span
                    key={`${e.prayer}-${e.kind}`}
                    className={`week-block ${e.kind}`}
                    style={{ top: pct(start), height: `max(${e.kind === "drive" ? 10 : 16}px, ${((end - start) / span) * 100}%)` }}
                  />
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Waiting() {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [still] = useState(reducedMotion);

  useEffect(() => {
    if (still) return;
    let stopped = false;
    let tries = 0;
    async function ask() {
      tries += 1;
      try {
        const answer = await api.preview();
        if (!stopped) setPreview(answer.events.length ? answer : typicalWeek());
      } catch {
        // Setup may still be saving its last answers. Ask again, then give up and show a typical week.
        if (stopped) return;
        if (tries < ASK_TIMES) window.setTimeout(ask, ASK_EVERY_MS);
        else setPreview(typicalWeek());
      }
    }
    void ask();
    return () => {
      stopped = true;
    };
  }, [still]);

  if (still) return <div className="spinner" aria-hidden="true" />;
  return preview ? <WeekFilling preview={preview} /> : <p className="adding-caption" aria-hidden="true">Getting started…</p>;
}

export function AddingPage() {
  const [failed, setFailed] = useState<string | null>(null);
  // Opened by hand, or the setup tab is gone: nothing will come. Known straight
  // away, so the week (and its call to the API) never starts.
  const [alone] = useState(() => !window.opener);

  useEffect(() => {
    const opener = window.opener as Window | null;
    if (!opener) return;
    // The result can arrive twice: once when it's ready, and again in
    // reply to "ready". Only the first one counts.
    let done = false;
    function onMessage(event: MessageEvent) {
      // Only the setup tab that opened this one, on our own site.
      if (done || event.source !== opener || event.origin !== window.location.origin) return;
      const data = event.data;
      if (data?.type === "open" && typeof data.url === "string" && data.url.startsWith(GOOGLE_CALENDAR_PREFIX)) {
        done = true;
        // Cut the link back to our tab, so Google's page can't reach it.
        window.opener = null;
        window.location.replace(data.url);
      } else if (data?.type === "failed") {
        done = true;
        setFailed(String(data.message));
      }
    }
    window.addEventListener("message", onMessage);
    opener.postMessage({ type: "ready" }, window.location.origin);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  if (failed !== null || alone) {
    return (
      <main className="page narrow">
        {failed !== null ? (
          <>
            <h1>Something went wrong</h1>
            <p className="error" role="alert">
              {failed}
            </p>
            <p>
              <a href="/">Back to Settings</a>
            </p>
          </>
        ) : (
          <>
            <h1>Nothing to add here</h1>
            <p>
              <a href="/">Go to Settings</a>
            </p>
          </>
        )}
      </main>
    );
  }

  return (
    <main className="adding">
      <h1>Adding your prayers to Google Calendar...</h1>
      <p className="adding-wait one-line">This can take up to a minute.</p>
      <Waiting />
    </main>
  );
}
