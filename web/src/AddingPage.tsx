// The new tab that opens on Finish (see finishTab.ts). It shows a message
// until the setup tab says the first calendar update is done, then opens
// Google Calendar here. It never calls the API itself.
//
// While it waits, a little week calendar fills up with prayer blocks, one
// by one, in the user's prayer colour, then starts again. It's all CSS
// (see .mini-week in styles.css). Users who turn off motion get a spinner.

import { useEffect, useState, type CSSProperties } from "react";
import { GOOGLE_CALENDAR_PREFIX } from "./googleCalendar";
import { GOOGLE_COLOURS } from "./labels";

const DAYS = ["M", "T", "W", "T", "F", "S", "S"];
const PRAYERS_PER_DAY = 5;

// Only one of Google's 11 colour IDs counts. Anything else uses the app's green.
function prayerColour(): string | null {
  const id = new URLSearchParams(window.location.search).get("colour");
  return GOOGLE_COLOURS.find((c) => c.id === id)?.hex ?? null;
}

function MiniWeek() {
  const colour = prayerColour();
  return (
    <div aria-hidden="true">
      <div className="mini-week" style={colour ? ({ "--prayer": colour } as CSSProperties) : undefined}>
        {DAYS.map((day, d) => (
          <span key={`day-${d}`} className="mini-day">
            {day}
          </span>
        ))}
        {/* Row by row in the grid, but each block's turn (--i) goes day by day. */}
        {Array.from({ length: PRAYERS_PER_DAY }, (_, p) =>
          DAYS.map((_, d) => (
            <span key={`${d}-${p}`} className="mini-cell">
              <span className="mini-block" style={{ "--i": d * PRAYERS_PER_DAY + p } as CSSProperties} />
            </span>
          )),
        )}
      </div>
      <div className="spinner" />
    </div>
  );
}

export function AddingPage() {
  const [failed, setFailed] = useState<string | null>(null);
  const [alone, setAlone] = useState(false);

  useEffect(() => {
    const opener = window.opener as Window | null;
    if (!opener) {
      // Opened by hand, or the setup tab is gone: nothing will come.
      setAlone(true);
      return;
    }
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

  return (
    <main className="page narrow adding">
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
      ) : alone ? (
        <>
          <h1>Nothing to add here</h1>
          <p>
            <a href="/">Go to Settings</a>
          </p>
        </>
      ) : (
        <>
          <h1 className="one-line">Adding your prayers to Google Calendar...</h1>
          <p className="hint one-line">This can take up to a minute.</p>
          <MiniWeek />
        </>
      )}
    </main>
  );
}
