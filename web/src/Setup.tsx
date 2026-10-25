// Setup asks 4 questions, one per page: location, main masjid, the weekly
// grid (skipped for "I pray at home"), and an optional step that can be
// skipped (how early, short name, colours). It matches the landing page:
// the list of steps on the left and the question on the right. On a phone,
// the list becomes one line at the top.
//
// Finish (or Skip) on the last step opens a new tab for Google Calendar,
// inside the click. Then App fills the calendar and this tab goes to Settings.

import { useEffect, useRef, useState } from "react";
import { openFinishTab, NO_TAB, type FinishTab } from "./finishTab";
import { OsmFooter } from "./OsmFooter";
import { LocationStep } from "./steps/LocationStep";
import { MasjidStep } from "./steps/MasjidStep";
import { OptionalStep } from "./steps/OptionalStep";
import { WeeklyStep } from "./steps/WeeklyStep";
import type { SaveResponse, Settings, Step } from "./types";

type Props = {
  initial: Settings;
  // Every question is answered. App fills the calendar.
  onDone: (settings: Settings, tab: FinishTab) => void;
};

const STEPS: { step: Step; name: string }[] = [
  { step: "address", name: "Location" },
  { step: "masjid", name: "Masjid" },
  { step: "weekly", name: "Weekly prayers" },
  { step: "optional", name: "Optional" },
];

export function masjidLabel(settings: Settings): string {
  return settings.main_masjid_short_name || settings.main_masjid?.name || "your masjid";
}

export function Setup({ initial, onDone }: Props) {
  const [settings, setSettings] = useState(initial);
  // Start at the first question not answered yet. Back can go to earlier ones.
  const [step, setStep] = useState<Step | "finish">(initial.missing[0] ?? "finish");
  const started = useRef(false);
  // The Google Calendar tab, opened by the Finish or Skip click.
  const tab = useRef<FinishTab>(NO_TAB);

  const index = step === "finish" ? STEPS.length : STEPS.findIndex((s) => s.step === step);
  const atHome = settings.main_masjid_choice === "home";

  // Every question was answered last time, but the calendar wasn't filled
  // (for example, the tab was closed). Finish now, with no new tab, since
  // there was no click. The ref stops React's development mode from calling it twice.
  useEffect(() => {
    if (step === "finish" && !started.current) {
      started.current = true;
      onDone(settings, NO_TAB);
    }
    // Only on the first render.
  }, []);

  function next(saved: Settings) {
    setSettings(saved);
    if (step === "address") setStep("masjid");
    else if (step === "masjid") setStep(saved.main_masjid_choice === "home" ? "optional" : "weekly");
    else if (step === "weekly") setStep("optional");
    else onDone(saved, tab.current);
  }

  function openTab() {
    tab.current = openFinishTab();
  }

  function closeTab() {
    tab.current.close();
    tab.current = NO_TAB;
  }

  const saved = (response: SaveResponse) => next(response.settings);

  function back() {
    if (step === "masjid") setStep("address");
    if (step === "weekly") setStep("masjid");
    if (step === "optional") setStep(atHome ? "masjid" : "weekly");
  }

  return (
    <div className="page-with-footer">
      <div className="setup">
        <aside className="setup-steps" aria-label="Setup steps">
          <h2 className="setup-title">Setup</h2>
          <ol>
            {STEPS.map((s, i) => {
              const skipped = s.step === "weekly" && atHome && i !== index;
              const state = i === index ? "current" : skipped ? "skipped" : i < index ? "done" : "todo";
              return (
                <li key={s.step} className={state} aria-current={state === "current" ? "step" : undefined}>
                  <span className="dot" aria-hidden="true">
                    {state === "done" ? "✓" : i + 1}
                  </span>
                  {s.name}
                  {skipped && <span className="visually-hidden"> (skipped)</span>}
                </li>
              );
            })}
          </ol>
        </aside>

        <main className="setup-question">
          <div className="question-top">
            {step === "masjid" || step === "weekly" || step === "optional" ? (
              <button type="button" className="back" onClick={back}>
                ← Back
              </button>
            ) : (
              <span />
            )}
            {step !== "finish" && (
              <p className="phone-progress">
                Setup · Step {index + 1} of {STEPS.length}
              </p>
            )}
          </div>

          {step === "address" && (
            <LocationStep page current={settings.place_name} onSaved={saved} onKeep={() => next(settings)} keepLabel="Next" />
          )}
          {step === "masjid" && <MasjidStep page settings={settings} onSaved={saved} submitLabel="Next" />}
          {step === "weekly" && (
            <WeeklyStep page initial={settings.weekly} masjidLabel={masjidLabel(settings)} onSaved={saved} submitLabel="Next" />
          )}
          {step === "optional" && (
            <OptionalStep page settings={settings} onSaved={saved} submitLabel="Finish" canSkip
              onFinishClick={openTab} onSaveFailed={closeTab} />
          )}
        </main>
      </div>
      <OsmFooter />
    </div>
  );
}
