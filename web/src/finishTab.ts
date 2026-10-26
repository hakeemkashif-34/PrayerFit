// The new tab that opens when setup finishes.
//
// Browsers only allow a new tab straight from a click, so the tab opens
// inside the Finish click, before the calendar update starts. It shows our
// own "/adding" page. When the update finishes, this tab tells it what to
// do next with postMessage:
//   { type: "open", url }        go to Google Calendar
//   { type: "failed", message }  show the error
// The new tab says "ready" once its page has loaded, and gets the result
// again then, so a quick update can't finish before the tab is listening.

export type FinishTab = {
  // "blocked" means the browser stopped the new tab. "none" means no click
  // started it, like finishing setup that was answered in an earlier visit.
  state: "opened" | "blocked" | "none";
  succeed: (url: string) => void;
  fail: (message: string) => void;
  close: () => void;
};

const nothing = () => {};

export const NO_TAB: FinishTab = { state: "none", succeed: nothing, fail: nothing, close: nothing };

// Call this inside the click handler, before any await. colourId is the
// prayer colour the user picked, so the page's little calendar uses it.
export function openFinishTab(colourId: string | null): FinishTab {
  const tab = window.open(colourId ? `/adding?colour=${encodeURIComponent(colourId)}` : "/adding", "_blank");
  if (!tab) return { ...NO_TAB, state: "blocked" };

  let result: { type: "open"; url: string } | { type: "failed"; message: string } | null = null;
  const send = () => {
    if (result && !tab.closed) tab.postMessage(result, window.location.origin);
  };
  const onMessage = (event: MessageEvent) => {
    // Only our own page, in the tab we opened.
    if (event.source === tab && event.origin === window.location.origin && event.data?.type === "ready") send();
  };
  window.addEventListener("message", onMessage);

  return {
    state: "opened",
    succeed: (url) => {
      result = { type: "open", url };
      send();
    },
    fail: (message) => {
      result = { type: "failed", message };
      send();
    },
    close: () => {
      window.removeEventListener("message", onMessage);
      tab.close();
    },
  };
}
