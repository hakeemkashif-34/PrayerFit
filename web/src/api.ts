// Every call to the backend goes through here.
// The session cookie is HttpOnly, so this code never sees it. The browser
// sends it because the website and the API are the same site.

import type { CalendarUpdate, Masjid, MasjidSuggestion, Me, SaveResponse, Settings, Suggestions } from "./types";

export class ApiError extends Error {
  status: number;
  // "not_signed_in", "google_sign_in_expired", or "calendar_access_missing"
  reason: string | undefined;

  constructor(status: number, message: string, reason?: string) {
    super(message);
    this.status = status;
    this.reason = reason;
  }
}

// The API tells the website when Google sign-in has expired, from any call.
let onSignInExpired: () => void = () => {};
export function whenSignInExpires(handler: () => void) {
  onSignInExpired = handler;
}

function messageFrom(status: number, detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return "Check what you typed and try again.";
  if (detail && typeof detail === "object" && "message" in detail) return String(detail.message);
  return `Something went wrong (error ${status}). Try again.`;
}

async function request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    method,
    signal,
    credentials: "same-origin",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    const reason = detail && typeof detail === "object" && "reason" in detail ? detail.reason : undefined;
    if (reason === "google_sign_in_expired" || reason === "calendar_access_missing") onSignInExpired();
    throw new ApiError(response.status, messageFrom(response.status, detail), reason);
  }
  return data as T;
}

export const api = {
  me: () => request<Me>("GET", "/api/me"),
  settings: () => request<Settings>("GET", "/api/settings"),
  // signal lets the website cancel a search when the user types again.
  suggestLocations: (query: string, signal?: AbortSignal) =>
    request<Suggestions>("POST", "/api/setup/location/suggest", { query }, signal),
  saveLocation: (query: string, index: number) =>
    request<SaveResponse>("PUT", "/api/settings/location", { query, index }),
  saveMethods: (method: string, asr_method: string) =>
    request<SaveResponse>("PUT", "/api/settings/methods", { method, asr_method }),
  suggestMasjids: (query: string, signal?: AbortSignal) =>
    request<{ suggestions: MasjidSuggestion[] }>("POST", "/api/setup/masjid/suggest", { query }, signal),
  // Saves the picked suggestion as a masjid, so it can be the main or a Jumuah masjid.
  masjidFromSuggestion: (query: string, index: number) =>
    request<Masjid>("POST", "/api/masjids/from-suggestion", { query, index }),
  saveMainMasjid: (body: { choice: "masjid" | "home"; masjid_id?: string; short_name?: string }) =>
    request<SaveResponse>("PUT", "/api/settings/main-masjid", body),
  saveWeekly: (days: Settings["weekly"]) => request<SaveResponse>("PUT", "/api/settings/weekly", { days }),
  saveJumuah: (masjid_ids: string[]) => request<SaveResponse>("PUT", "/api/settings/jumuah", { masjid_ids }),
  finishSetup: () => request<SaveResponse>("POST", "/api/setup/finish"),
  syncCalendar: () => request<CalendarUpdate>("POST", "/api/calendar/sync"),
  // /auth/ goes straight to the backend, like the sign-in links.
  signOut: () => request<void>("POST", "/auth/logout"),
};

export const SIGN_IN_URL = "/auth/google/login";
