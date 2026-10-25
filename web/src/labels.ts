// Words shown on the page for the values the API uses.

import type { Masjid, Prayer } from "./types";

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

export const METHODS: { value: string; name: string; about: string }[] = [
  { value: "isna", name: "ISNA", about: "Fajr and Isha at 15°. Most masjids in North America use this." },
  { value: "mwl", name: "Muslim World League", about: "Fajr at 18°, Isha at 17°. Common in Europe." },
  { value: "egyptian", name: "Egyptian", about: "Fajr at 19.5°, Isha at 17.5°. Common in Africa and the Middle East." },
  { value: "karachi", name: "Karachi", about: "Fajr and Isha at 18°. Common in South Asia." },
  { value: "umm_al_qura", name: "Umm al-Qura", about: "Fajr at 18.5°, Isha 90 minutes after Maghrib. Used in Saudi Arabia." },
];

export const ASR_METHODS: { value: string; name: string; about: string }[] = [
  { value: "standard", name: "Standard", about: "A shadow as long as the object. Shafi'i, Maliki, and Hanbali." },
  { value: "hanafi", name: "Hanafi", about: "A shadow twice as long as the object, so Asr starts later." },
];

export function methodName(value: string): string {
  return METHODS.find((m) => m.value === value)?.name ?? value;
}

export function asrName(value: string): string {
  return ASR_METHODS.find((m) => m.value === value)?.name ?? value;
}

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
