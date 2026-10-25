// Setup asks 3 questions, one per page: location, main masjid, and the
// weekly grid (skipped for "I pray at home"). Each page has a Back button.
// Straight after the last answer, the calendar is filled.

import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { LocationStep } from "./steps/LocationStep";
import { MasjidStep } from "./steps/MasjidStep";
import { WeeklyStep } from "./steps/WeeklyStep";
import type { CalendarUpdate, SaveResponse, Settings, Step } from "./types";

type Props = {
  initial: Settings;
  onFinished: (settings: Settings, calendar: CalendarUpdate | null) => void;
};

const STEPS: Step[] = ["address", "masjid", "weekly"];

export function masjidLabel(settings: Settings): string {
  return settings.main_masjid_short_name || settings.main_masjid?.name || "your masjid";
}

export function Setup({ initial, onFinished }: Props) {
  const [settings, setSettings] = useState(initial);
  // Start at the first question not answered yet. Back can go to earlier ones.
  const [step, setStep] = useState<Step | "finish">(initial.missing[0] ?? "finish");
  const [error, setError] = useState("");

  const number = step === "finish" ? STEPS.length : STEPS.indexOf(step) + 1;
  const started = useRef(false);

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
    else if (step === "masjid" && saved.main_masjid_choice !== "home") setStep("weekly");
    else void finish();
  }

  const saved = (response: SaveResponse) => next(response.settings);

  function back() {
    if (step === "masjid") setStep("address");
    if (step === "weekly") setStep("masjid");
  }

  return (
    <main className="page question">
      <div className="question-top">
        {step === "masjid" || step === "weekly" ? (
          <button type="button" className="back" onClick={back}>
            ← Back
          </button>
        ) : (
          <span />
        )}
        {step !== "finish" && (
          <p className="progress">
            Step {number} of {STEPS.length}
          </p>
        )}
      </div>

      {step === "address" && (
        <LocationStep page current={settings.place_name} onSaved={saved} onKeep={() => next(settings)} keepLabel="Next" />
      )}
      {step === "masjid" && (
        <MasjidStep page settings={settings} onSaved={saved} submitLabel="Next" />
      )}
      {step === "weekly" && (
        <WeeklyStep page initial={settings.weekly} masjidLabel={masjidLabel(settings)} onSaved={saved} submitLabel="Finish" />
      )}
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
  );
}
