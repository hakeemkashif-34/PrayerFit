// Setup is 2 pages. Page 1, "Required": location, main masjid (or "I pray
// at home"), and the weekly grid. Page 2, "Optional": short name, how
// early, commute time, colours, and the Jumuah chooser. It matches the
// landing page: the list of pages on the left and the questions on the
// right. On a phone, the list becomes one line at the top.
//
// Finish (or Skip) on page 2 opens a new tab for Google Calendar, inside
// the click. Then App fills the calendar and this tab goes to Settings.

import { useEffect, useRef, useState } from "react";
import { openFinishTab, NO_TAB, type FinishTab } from "./finishTab";
import { OsmFooter } from "./OsmFooter";
import { OptionalPage } from "./steps/OptionalPage";
import { RequiredPage } from "./steps/RequiredPage";
import type { Settings } from "./types";

type Props = {
  initial: Settings;
  // Every question is answered. App fills the calendar.
  onDone: (settings: Settings, tab: FinishTab) => void;
};

type Page = "required" | "optional";

const PAGES: { page: Page; name: string }[] = [
  { page: "required", name: "Required" },
  { page: "optional", name: "Optional" },
];

function firstPage(settings: Settings): Page | "finish" {
  if (settings.missing.some((step) => step !== "optional")) return "required";
  return settings.missing.includes("optional") ? "optional" : "finish";
}

export function Setup({ initial, onDone }: Props) {
  const [settings, setSettings] = useState(initial);
  const [page, setPage] = useState<Page | "finish">(firstPage(initial));
  // Page 2 stays on the page once it's been shown (just hidden), so Back
  // and Next again keep everything typed there.
  const [optionalShown, setOptionalShown] = useState(page === "optional");
  const started = useRef(false);
  // The Google Calendar tab, opened by the Finish or Skip click.
  const tab = useRef<FinishTab>(NO_TAB);

  const index = page === "finish" ? PAGES.length : PAGES.findIndex((p) => p.page === page);

  // Every question was answered last time, but the calendar wasn't filled
  // (for example, the tab was closed). Finish now, with no new tab, since
  // there was no click. The ref stops React's development mode from calling it twice.
  useEffect(() => {
    if (page === "finish" && !started.current) {
      started.current = true;
      onDone(settings, NO_TAB);
    }
    // Only on the first render.
  }, []);

  function toOptional(saved: Settings) {
    setSettings(saved);
    setPage("optional");
    setOptionalShown(true);
    window.scrollTo(0, 0);
  }

  function openTab() {
    tab.current = openFinishTab();
  }

  function closeTab() {
    tab.current.close();
    tab.current = NO_TAB;
  }

  return (
    <div className="page-with-footer">
      <div className="setup">
        <aside className="setup-steps" aria-label="Setup steps">
          <h2 className="setup-title">Setup</h2>
          <ol>
            {PAGES.map((p, i) => {
              const state = i === index ? "current" : i < index ? "done" : "todo";
              return (
                <li key={p.page} className={state} aria-current={state === "current" ? "step" : undefined}>
                  <span className="dot" aria-hidden="true">
                    {state === "done" ? "✓" : i + 1}
                  </span>
                  {p.name}
                </li>
              );
            })}
          </ol>
        </aside>

        <main className="setup-question">
          <div className="question-top">
            {page === "optional" ? (
              <button type="button" className="back" onClick={() => setPage("required")}>
                ← Back
              </button>
            ) : (
              <span />
            )}
            {page !== "finish" && (
              <p className="phone-progress">
                Setup · Step {index + 1} of {PAGES.length}
              </p>
            )}
          </div>

          {page === "required" && <RequiredPage settings={settings} onChange={setSettings} onNext={toOptional} />}
          {optionalShown && (
            <div hidden={page !== "optional"}>
              <OptionalPage settings={settings} active={page === "optional"} onFinishClick={openTab}
                onSaveFailed={closeTab} onSaved={(saved) => onDone(saved, tab.current)} />
            </div>
          )}
        </main>
      </div>
      <OsmFooter />
    </div>
  );
}
