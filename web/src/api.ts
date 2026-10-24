// Every call to the backend goes through here.
// The session cookie is HttpOnly, so this code never sees it. The browser
// sends it because the website and the API are the same site.

import type { CalendarUpdate, FoundAddress, Me, Nearby, SaveResponse, Settings } from "./types";

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

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
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
  searchAddress: (address: string) => request<FoundAddress>("POST", "/api/setup/address/search", { address }),
  saveAddress: (address: string) => request<SaveResponse>("PUT", "/api/settings/address", { address }),
  saveMethods: (method: string, asr_method: string) =>
    request<SaveResponse>("PUT", "/api/settings/methods", { method, asr_method }),
  nearbyMasjids: () => request<Nearby>("GET", "/api/masjids/nearby"),
  saveMainMasjid: (body: {
    choice: "masjid" | "custom" | "home";
    masjid_id?: string;
    name?: string;
    address?: string;
    short_name?: string;
  }) => request<SaveResponse>("PUT", "/api/settings/main-masjid", body),
  saveWeekly: (days: Settings["weekly"]) => request<SaveResponse>("PUT", "/api/settings/weekly", { days }),
  saveJumuah: (masjid_ids: string[]) => request<SaveResponse>("PUT", "/api/settings/jumuah", { masjid_ids }),
  finishSetup: () => request<SaveResponse>("POST", "/api/setup/finish"),
  syncCalendar: () => request<CalendarUpdate>("POST", "/api/calendar/sync"),
  // /auth/ goes straight to the backend, like the sign-in links.
  signOut: () => request<void>("POST", "/auth/logout"),
};

export const SIGN_IN_URL = "/auth/google/login";
