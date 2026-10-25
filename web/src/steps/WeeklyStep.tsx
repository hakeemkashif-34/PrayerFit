// Question 3: which prayers are usually at the masjid. Prayers are rows,
// days are columns, Monday to Sunday. Ticked means at the masjid,
// unticked means at home.

import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { PRAYER_NAMES, PRAYERS, WEEKDAYS, WEEKDAYS_SHORT } from "../labels";
import type { Prayer, SaveResponse, WeekdayPrayers } from "../types";

type Props = {
  initial: WeekdayPrayers[];
  masjidLabel: string;
  // Show the question as the page's main heading (setup) or a card heading (settings).
  page?: boolean;
  submitLabel?: string;
  onSaved: (response: SaveResponse) => void;
  onCancel?: () => void;
};

function emptyWeek(): WeekdayPrayers[] {
  return WEEKDAYS.map((_, weekday) => ({ weekday, fajr: false, dhuhr: false, asr: false, maghrib: false, isha: false }));
}

export function WeeklyStep({ initial, masjidLabel, page = false, submitLabel = "Save", onSaved, onCancel }: Props) {
  const [days, setDays] = useState(initial.length === 7 ? initial : emptyWeek());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const Heading = page ? "h1" : "h2";

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
      <Heading id="weekly-title">Which prayers do you usually pray at {masjidLabel}?</Heading>
      <p className="hint">Ticked means at the masjid. Unticked means at home.</p>
      <table className="grid">
        <thead>
          <tr>
            <th scope="col">
              <span className="visually-hidden">Prayer</span>
            </th>
            {WEEKDAYS_SHORT.map((day, weekday) => (
              <th key={day} scope="col">
                <abbr title={WEEKDAYS[weekday]}>{day}</abbr>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {PRAYERS.map((prayer) => (
            <tr key={prayer}>
              <th scope="row">{PRAYER_NAMES[prayer]}</th>
              {days.map((day) => (
                <td key={day.weekday}>
                  <input
                    type="checkbox"
                    aria-label={`${PRAYER_NAMES[prayer]} on ${WEEKDAYS[day.weekday]} at the masjid`}
                    checked={day[prayer]}
                    onChange={() => toggle(day.weekday, prayer)}
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
          {busy ? "Saving…" : submitLabel}
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
