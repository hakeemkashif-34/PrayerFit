// Words shown on the page for the values the API uses.

import type { Masjid, Prayer, Settings } from "./types";

export const PRAYERS: Prayer[] = ["fajr", "dhuhr", "asr", "maghrib", "isha"];
export const PRAYER_NAMES: Record<Prayer, string> = {
  fajr: "Fajr",
  dhuhr: "Dhuhr",
  asr: "Asr",
  maghrib: "Maghrib",
  isha: "Isha",
};
// 0 is Monday, the same as the backend.
export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
export const WEEKDAYS_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// A masjid picked by its address has no name, so its address is shown.
export function masjidName(masjid: Masjid): string {
  return masjid.name ?? masjid.address ?? "Your masjid";
}

export function distanceText(km: number | null): string {
  return km === null ? "" : `${km} km away`;
}

// Fixed messages for each sign-in error code from the backend.
export const SIGN_IN_ERRORS: Record<string, string> = {
  cancelled: "Google sign-in was cancelled. Try again when you're ready.",
  expired: "That sign-in took too long or was already used. Try again.",
  state: "That sign-in didn't match this browser. Try again.",
  google: "Google didn't accept the sign-in. Try again.",
};

// Google Calendar's fixed event colours, with the names Google shows, in
// the order its own colour menu lists them. The ID is what goes to Google.
// null means the Prayers calendar's own colour.
export const GOOGLE_COLOURS: { id: string; name: string; hex: string }[] = [
  { id: "11", name: "Tomato", hex: "#d50000" },
  { id: "4", name: "Flamingo", hex: "#e67c73" },
  { id: "6", name: "Tangerine", hex: "#f4511e" },
  { id: "5", name: "Banana", hex: "#f6bf26" },
  { id: "2", name: "Sage", hex: "#33b679" },
  { id: "10", name: "Basil", hex: "#0b8043" },
  { id: "7", name: "Peacock", hex: "#039be5" },
  { id: "9", name: "Blueberry", hex: "#3f51b5" },
  { id: "1", name: "Lavender", hex: "#7986cb" },
  { id: "3", name: "Grape", hex: "#8e24aa" },
  { id: "8", name: "Graphite", hex: "#616161" },
];
export const CALENDAR_COLOUR = "Calendar colour";
// The optional step's defaults, the same as the backend's: 5 minutes early
// for prayers and for Jumuah, and Basil (Google's green) for prayer and drive blocks.
export const DEFAULT_ARRIVE_EARLY = 5;
export const DEFAULT_JUMUAH_ARRIVE_EARLY = 5;
export const DEFAULT_COLOUR = "10";

export function colourName(id: string | null): string {
  return GOOGLE_COLOURS.find((c) => c.id === id)?.name ?? CALENDAR_COLOUR;
}

export function earlyText(minutes: number): string {
  if (minutes === 0) return "Arrive at iqamah time";
  return `Arrive ${minutes} min before iqamah`;
}

export function jumuahEarlyText(minutes: number): string {
  if (minutes === 0) return "Arrive at Jumuah time";
  return `Arrive ${minutes} min before Jumuah`;
}

// The masjid's name in event titles: the short name if there is one.
export function masjidLabel(settings: Settings): string {
  return settings.main_masjid_short_name || settings.main_masjid?.name || "your masjid";
}

// "2026-10-30T13:30:00-04:00" -> "1:30 PM", in the user's time zone.
export function timeText(iso: string, timeZone: string): string {
  const parts = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", hour12: true, timeZone })
    .formatToParts(new Date(iso));
  const part = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  // Built from parts, since browsers put different spaces before "PM".
  return `${part("hour")}:${part("minute")} ${part("dayPeriod").toUpperCase()}`;
}

// "1:30 to 2:15 PM", or "11:30 AM to 12:15 PM" when AM and PM differ.
export function spanText(startIso: string, endIso: string, timeZone: string): string {
  const start = timeText(startIso, timeZone);
  const end = timeText(endIso, timeZone);
  return start.slice(-2) === end.slice(-2) ? `${start.slice(0, -3)} to ${end}` : `${start} to ${end}`;
}

// "5" -> 5. Anything that isn't a whole number from min to max is null.
export function wholeMinutes(text: string, min: number, max: number): number | null {
  if (!/^\d{1,3}$/.test(text.trim())) return null;
  const minutes = Number(text.trim());
  return minutes >= min && minutes <= max ? minutes : null;
}

export const MAX_EARLY = 60;
export const EARLY_ERROR = `Enter a whole number of minutes from 0 to ${MAX_EARLY}.`;

// Minutes since midnight on the clock in that time zone: "1:30 PM" -> 810.
export function minutesIntoDay(iso: string, timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", hourCycle: "h23", timeZone })
    .formatToParts(new Date(iso));
  const part = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? 0);
  return part("hour") * 60 + part("minute");
}

// 660 -> "11 AM", 720 -> "12 PM".
export function hourText(minutes: number): string {
  const hour = Math.floor(minutes / 60) % 24;
  return `${hour % 12 || 12} ${hour < 12 ? "AM" : "PM"}`;
}
