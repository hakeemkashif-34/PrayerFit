// Decides which screen to show: sign in, sign in again, setup, or settings.

import { useEffect, useState } from "react";
import { api, ApiError, whenSignInExpires } from "./api";
import { goToGoogleCalendar } from "./googleCalendar";
import { SettingsPage } from "./SettingsPage";
import { Setup } from "./Setup";
import { SignIn } from "./SignIn";
import type { CalendarUpdate, Me, Settings } from "./types";

type View =
  | { kind: "loading" }
  | { kind: "signed-out" }
  | { kind: "expired" }
  | { kind: "setup"; settings: Settings }
  | { kind: "settings"; me: Me; settings: Settings; calendar: CalendarUpdate | null }
  | { kind: "error"; message: string };

export function App() {
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
        <Setup
          initial={view.settings}
          onFinished={async (settings, calendar) => {
            const me = await api.me();
            // Every prayer reached Google, so show them there. Setup keeps
            // showing "Adding your prayers..." until the browser leaves.
            if (calendar?.status === "updated") return goToGoogleCalendar(me.email);
            // Otherwise stay here: Settings shows what went wrong, with Try again.
            setView({ kind: "settings", me, settings, calendar });
          }}
        />
      );
    case "settings":
      return (
        <SettingsPage
          email={view.me.email}
          initial={view.settings}
          initialCalendar={view.calendar}
          onSignedOut={() => setView({ kind: "signed-out" })}
        />
      );
  }
}
