// Decides which screen to show: sign in, sign in again, setup, or settings.

import { useEffect, useState } from "react";
import { AddingPage } from "./AddingPage";
import { api, ApiError, whenSignInExpires } from "./api";
import { NO_TAB, type FinishTab } from "./finishTab";
import { googleCalendarUrl } from "./googleCalendar";
import { SettingsPage } from "./SettingsPage";
import { Setup } from "./Setup";
import { SignIn } from "./SignIn";
import { StatsPage } from "./StatsPage";
import type { CalendarUpdate, Me, Settings } from "./types";

type View =
  | { kind: "loading" }
  | { kind: "signed-out" }
  | { kind: "expired" }
  | { kind: "setup"; settings: Settings }
  | {
      kind: "settings";
      me: Me;
      settings: Settings;
      calendar: CalendarUpdate | null;
      // The browser blocked the Google Calendar tab, so Settings says so.
      tabBlocked?: boolean;
      // Finishing setup failed before the calendar update even ran. Try again finishes it.
      retryFinish?: () => void;
    }
  | { kind: "error"; message: string };

const ADDING: CalendarUpdate = {
  status: "adding", sent: 0, waiting: 0, message: "Adding your prayers to Google Calendar...",
};

export function App() {
  // The new tab opened on Finish (see finishTab.ts) is its own small page.
  if (window.location.pathname === "/adding") return <AddingPage />;
  // The private stats page. It isn't linked from anywhere.
  if (window.location.pathname === "/stats") return <StatsPage />;
  return <Main />;
}

function Main() {
  const [view, setView] = useState<View>({ kind: "loading" });
  const errorCode = new URLSearchParams(window.location.search).get("sign_in_error");

  useEffect(() => {
    // Any call that finds Google's sign-in expired switches to "Sign in again".
    whenSignInExpires(() => setView({ kind: "expired" }));
    void load();
  }, []);

  async function load() {
    try {
      const me = await api.me();
      if (me.google_sign_in_needed) return setView({ kind: "expired" });
      const settings = await api.settings();
      setView(me.setup_complete ? { kind: "settings", me, settings, calendar: null } : { kind: "setup", settings });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401 && e.reason === "not_signed_in") return setView({ kind: "signed-out" });
      if (e instanceof ApiError && e.reason !== undefined) return; // already showing "Sign in again"
      setView({ kind: "error", message: e instanceof ApiError ? e.message : "Couldn't reach the server. Refresh to try again." });
    }
  }

  // Every answer is in. This tab goes to Settings straight away, and the
  // first calendar update runs. The new tab (if any) opens Google Calendar
  // when it's done, or shows the error. This tab is never sent away.
  async function finish(settings: Settings, tab: FinishTab) {
    let me: Me;
    try {
      me = await api.me();
    } catch (e) {
      const message = e instanceof ApiError ? e.message : "Couldn't reach the server. Refresh to try again.";
      tab.fail(message);
      return setView({ kind: "error", message });
    }
    setView({ kind: "settings", me, settings, calendar: ADDING });
    try {
      const response = await api.finishSetup();
      const calendar = response.calendar;
      if (calendar?.status === "updated") tab.succeed(googleCalendarUrl(me.email));
      else tab.fail(calendar?.message ?? "Your calendar couldn't be filled. Try again.");
      setView({
        kind: "settings", me, settings: response.settings, calendar,
        tabBlocked: tab.state === "blocked" && calendar?.status === "updated",
      });
    } catch (e) {
      const message = e instanceof ApiError ? e.message : "Couldn't fill your calendar. Try again.";
      tab.fail(message);
      setView({
        kind: "settings", me, settings,
        calendar: { status: "waiting", sent: 0, waiting: 0, message },
        retryFinish: () => void finish(settings, NO_TAB),
      });
    }
  }

  switch (view.kind) {
    case "loading":
      return <main className="page narrow"><p className="hint">Loading…</p></main>;
    case "signed-out":
      return <SignIn errorCode={errorCode} />;
    case "expired":
      return <SignIn expired />;
    case "error":
      return (
        <main className="page narrow">
          <p className="error" role="alert">{view.message}</p>
        </main>
      );
    case "setup":
      return (
        <Setup initial={view.settings} onDone={(settings, tab) => void finish(settings, tab)} />
      );
    case "settings":
      return (
        <SettingsPage
          email={view.me.email}
          busyAccess={view.me.busy_access}
          initial={view.settings}
          initialCalendar={view.calendar}
          tabBlocked={view.tabBlocked ?? false}
          onRetry={view.retryFinish}
          onSignedOut={() => setView({ kind: "signed-out" })}
        />
      );
  }
}
