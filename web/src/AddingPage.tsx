// The new tab that opens on Finish (see finishTab.ts). It shows a message
// until the setup tab says the first calendar update is done, then opens
// Google Calendar here. It never calls the API itself.

import { useEffect, useState } from "react";
import { GOOGLE_CALENDAR_PREFIX } from "./googleCalendar";

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
      ) : alone ? (
        <>
          <h1>Nothing to add here</h1>
          <p>
            <a href="/">Go to Settings</a>
          </p>
        </>
      ) : (
        <>
          <h1>Adding your prayers to Google Calendar...</h1>
          <p className="hint">Adding today and the next 13 days. This can take up to 20 seconds.</p>
        </>
      )}
    </main>
  );
}
