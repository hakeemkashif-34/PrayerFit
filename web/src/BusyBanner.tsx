// For users who signed in before the app asked for free/busy access.
// Until they sign in again, Jumuah is picked as if their calendar were free.
// "Not now" is remembered in this browser only.

import { useState } from "react";
import { SIGN_IN_URL } from "./api";

const DISMISSED_KEY = "busy-banner-dismissed";

function wasDismissed(): boolean {
  // Storage can be blocked (private windows, strict settings). Then the banner just shows.
  try {
    return window.localStorage.getItem(DISMISSED_KEY) === "yes";
  } catch {
    return false;
  }
}

export function BusyBanner() {
  const [hidden, setHidden] = useState(wasDismissed);
  if (hidden) return null;

  function notNow() {
    try {
      window.localStorage.setItem(DISMISSED_KEY, "yes");
    } catch {
      // Not remembered, but it still goes away for now.
    }
    setHidden(true);
  }

  return (
    <section className="notice banner" aria-labelledby="busy-banner-title">
      <p id="busy-banner-title">
        <strong>Sign in again so your prayers can fit around your calendar.</strong>
      </p>
      <p>We only see when you're busy, never what your events are.</p>
      <div className="actions">
        <a className="button" href={SIGN_IN_URL}>
          Sign in again
        </a>
        <button type="button" className="secondary" onClick={notNow}>
          Not now
        </button>
      </div>
    </section>
  );
}
