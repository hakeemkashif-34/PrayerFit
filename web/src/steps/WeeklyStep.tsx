// Step 4: which prayers are usually at the masjid, Monday to Sunday.
// Ticked means at the masjid, unticked means at home.
// One row per day, so it fits on a phone without scrolling sideways.

import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { PRAYER_NAMES, PRAYERS, WEEKDAYS } from "../labels";
import type { Prayer, SaveResponse, WeekdayPrayers } from "../types";

type Props = {
  initial: WeekdayPrayers[];
  masjidLabel: string;
  onSaved: (response: SaveResponse) => void;
  onCancel?: () => void;
};

function emptyWeek(): WeekdayPrayers[] {
  return WEEKDAYS.map((_, weekday) => ({ weekday, fajr: false, dhuhr: false, asr: false, maghrib: false, isha: false }));
}

export function WeeklyStep({ initial, masjidLabel, onSaved, onCancel }: Props) {
  const [days, setDays] = useState(initial.length === 7 ? initial : emptyWeek());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function toggle(weekday: number, prayer: Prayer) {
    setDays((current) => current.map((d) => (d.weekday === weekday ? { ...d, [prayer]: !d[prayer] } : d)));
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onSaved(await api.saveWeekly(days));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save. Try again.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} aria-labelledby="weekly-title">
      <h2 id="weekly-title">Which prayers do you usually pray at {masjidLabel}?</h2>
      <p className="hint">Ticked means at the masjid. Unticked means at home.</p>
      <table className="grid">
        <thead>
          <tr>
            <th scope="col">
              <span className="visually-hidden">Day</span>
            </th>
            {PRAYERS.map((p) => (
              <th key={p} scope="col">
                {PRAYER_NAMES[p]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {days.map((day) => (
            <tr key={day.weekday}>
              <th scope="row">{WEEKDAYS[day.weekday].slice(0, 3)}</th>
              {PRAYERS.map((p) => (
                <td key={p}>
                  <input
                    type="checkbox"
                    aria-label={`${PRAYER_NAMES[p]} on ${WEEKDAYS[day.weekday]} at the masjid`}
                    checked={day[p]}
                    onChange={() => toggle(day.weekday, p)}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="actions">
        <button type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save"}
        </button>
        {onCancel && (
          <button type="button" className="secondary" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}
