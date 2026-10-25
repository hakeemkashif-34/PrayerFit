// Setup asks 4 questions, one per page: location, main masjid, the weekly
// grid (skipped for "I pray at home"), and an optional step that can be
// skipped (how early, short name, colours). It matches the landing page:
// the list of steps on the left and the question on the right. On a phone,
// the list becomes one line at the top. Straight after the last answer,
// the calendar is filled.

import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { OsmFooter } from "./OsmFooter";
import { LocationStep } from "./steps/LocationStep";
import { MasjidStep } from "./steps/MasjidStep";
import { OptionalStep } from "./steps/OptionalStep";
import { WeeklyStep } from "./steps/WeeklyStep";
import type { CalendarUpdate, SaveResponse, Settings, Step } from "./types";

type Props = {
  initial: Settings;
  onFinished: (settings: Settings, calendar: CalendarUpdate | null) => void;
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

export function Setup({ initial, onFinished }: Props) {
  const [settings, setSettings] = useState(initial);
  // Start at the first question not answered yet. Back can go to earlier ones.
  const [step, setStep] = useState<Step | "finish">(initial.missing[0] ?? "finish");
  const [error, setError] = useState("");
  const started = useRef(false);

  const index = step === "finish" ? STEPS.length : STEPS.findIndex((s) => s.step === step);
  const atHome = settings.main_masjid_choice === "home";

  // Every question was answered last time, but the calendar wasn't filled
  // (for example, the tab was closed). Finish now. The ref stops React's
  // development mode from calling it twice.
  useEffect(() => {
    if (step === "finish" && !started.current) {
      started.current = true;
      void finish();
    }
    // Only on the first render.
  }, []);

  async function finish() {
    setStep("finish");
    setError("");
    try {
      const response = await api.finishSetup();
      onFinished(response.settings, response.calendar);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't fill your calendar. Try again.");
    }
  }

  function next(saved: Settings) {
    setSettings(saved);
    if (step === "address") setStep("masjid");
    else if (step === "masjid") setStep(saved.main_masjid_choice === "home" ? "optional" : "weekly");
    else if (step === "weekly") setStep("optional");
    else void finish();
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
          {step === "optional" && <OptionalStep page settings={settings} onSaved={saved} submitLabel="Finish" canSkip />}
          {step === "finish" && (
            <section aria-labelledby="finish-title">
              <h1 id="finish-title">{error ? "Something went wrong" : "Filling your Prayers calendar…"}</h1>
              {!error && <p className="hint">Adding today and the next 13 days. This can take up to 20 seconds.</p>}
              {error && (
                <>
                  <p className="error" role="alert">
                    {error}
                  </p>
                  <div className="actions">
                    <button type="button" onClick={finish}>
                      Try again
                    </button>
                  </div>
                </>
              )}
            </section>
          )}
        </main>
      </div>
      <OsmFooter />
    </div>
  );
}
