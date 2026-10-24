// The setup questions, asked once, in order: address, methods, main masjid,
// weekly grid (skipped for "I pray at home"), and Jumuah masjids.

import { useState } from "react";
import { api, ApiError } from "./api";
import { AddressStep } from "./steps/AddressStep";
import { JumuahStep } from "./steps/JumuahStep";
import { MasjidStep } from "./steps/MasjidStep";
import { MethodsStep } from "./steps/MethodsStep";
import { WeeklyStep } from "./steps/WeeklyStep";
import type { CalendarUpdate, SaveResponse, Settings, Step } from "./types";

type Props = {
  initial: Settings;
  onFinished: (settings: Settings, calendar: CalendarUpdate | null) => void;
};

export function masjidLabel(settings: Settings): string {
  return settings.main_masjid_short_name || settings.main_masjid?.name || "your masjid";
}

export function Setup({ initial, onFinished }: Props) {
  const [settings, setSettings] = useState(initial);
  const [filling, setFilling] = useState(false);
  const [error, setError] = useState("");

  const steps: Step[] = ["address", "methods", "masjid", "weekly", "jumuah"].filter(
    (s) => !(s === "weekly" && settings.main_masjid_choice === "home"),
  ) as Step[];
  const current = settings.missing[0];
  const number = current ? steps.indexOf(current) + 1 : steps.length;
  const saved = (response: SaveResponse) => setSettings(response.settings);

  async function finish() {
    setFilling(true);
    setError("");
    try {
      const response = await api.finishSetup();
      onFinished(response.settings, response.calendar);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't finish. Try again.");
      setFilling(false);
    }
  }

  return (
    <main className="page">
      <h1>Set up your prayers</h1>
      {current && (
        <p className="progress">
          Step {number} of {steps.length}
        </p>
      )}
      <div className="card">
        {current === "address" && <AddressStep initial={settings.address} onSaved={saved} />}
        {current === "methods" && (
          <MethodsStep initialMethod={settings.method} initialAsr={settings.asr_method} onSaved={saved} />
        )}
        {current === "masjid" && <MasjidStep settings={settings} onSaved={saved} />}
        {current === "weekly" && (
          <WeeklyStep initial={settings.weekly} masjidLabel={masjidLabel(settings)} onSaved={saved} />
        )}
        {current === "jumuah" && <JumuahStep settings={settings} onSaved={saved} />}
        {!current && (
          <section aria-labelledby="finish-title">
            <h2 id="finish-title">All set</h2>
            <p>Next, the app fills your Prayers calendar with today and the next 13 days.</p>
            <div className="actions">
              <button type="button" onClick={finish} disabled={filling}>
                {filling ? "Filling your calendar…" : "Fill my calendar"}
              </button>
            </div>
            {filling && <p className="hint">This can take up to 20 seconds.</p>}
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
          </section>
        )}
      </div>
    </main>
  );
}
