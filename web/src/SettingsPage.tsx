// After setup: every saved setting on its own card, each with an Edit button.
// Edit opens the same step used in setup. Saving updates the calendar.

import { useState, type ReactNode } from "react";
import { api, ApiError } from "./api";
import { asrName, masjidName, methodName, PRAYER_NAMES, PRAYERS, WEEKDAYS } from "./labels";
import { masjidLabel } from "./Setup";
import { AddressStep } from "./steps/AddressStep";
import { JumuahStep } from "./steps/JumuahStep";
import { MasjidStep } from "./steps/MasjidStep";
import { MethodsStep } from "./steps/MethodsStep";
import { WeeklyStep } from "./steps/WeeklyStep";
import type { CalendarUpdate, SaveResponse, Settings, Step } from "./types";

type Props = {
  email: string;
  initial: Settings;
  initialCalendar: CalendarUpdate | null;
  onSignedOut: () => void;
};

export function SettingsPage({ email, initial, initialCalendar, onSignedOut }: Props) {
  const [settings, setSettings] = useState(initial);
  const [calendar, setCalendar] = useState(initialCalendar);
  // A masjid picked after "I pray at home" still needs the weekly grid.
  const [editing, setEditing] = useState<Step | null>(initial.missing[0] ?? null);
  const [busy, setBusy] = useState(false);

  function saved(response: SaveResponse) {
    setSettings(response.settings);
    setCalendar(response.calendar);
    setEditing(response.settings.missing[0] ?? null);
  }

  async function retry() {
    setBusy(true);
    try {
      setCalendar(await api.syncCalendar());
    } catch (e) {
      if (e instanceof ApiError) setCalendar({ status: "waiting", sent: 0, waiting: 0, message: e.message });
    } finally {
      setBusy(false);
    }
  }

  async function signOut() {
    setBusy(true);
    try {
      await api.signOut();
    } finally {
      onSignedOut();
    }
  }

  const cancel = () => setEditing(null);
  const atHome = settings.main_masjid_choice === "home";

  return (
    <main className="page">
      <header className="top">
        <h1>Your prayers</h1>
        <p className="hint">Signed in as {email}</p>
      </header>

      {calendar && (
        <p className={calendar.status === "updated" ? "notice" : "notice warning"} role="status">
          {calendar.message}{" "}
          {calendar.status === "waiting" && (
            <button type="button" className="link" onClick={retry} disabled={busy}>
              Try again
            </button>
          )}
        </p>
      )}

      <Card title="Address" step="address" editing={editing} onEdit={setEditing}
        edit={<AddressStep initial={settings.address} onSaved={saved} onCancel={cancel} />}>
        <p>{settings.place_name}</p>
        <p className="hint">Time zone: {settings.time_zone}</p>
      </Card>

      <Card title="Prayer time method" step="methods" editing={editing} onEdit={setEditing}
        edit={<MethodsStep initialMethod={settings.method} initialAsr={settings.asr_method} onSaved={saved} onCancel={cancel} />}>
        <p>{methodName(settings.method)}, {asrName(settings.asr_method)} Asr</p>
      </Card>

      <Card title="Main masjid" step="masjid" editing={editing} onEdit={setEditing}
        edit={<MasjidStep settings={settings} onSaved={saved} onCancel={cancel} />}>
        {atHome || !settings.main_masjid ? (
          <p>I pray at home</p>
        ) : (
          <>
            <p>
              {masjidName(settings.main_masjid)}
              {settings.main_masjid_short_name && ` (${settings.main_masjid_short_name})`}
            </p>
            <p className="hint">{settings.main_masjid.iqamah_status}</p>
          </>
        )}
      </Card>

      {!atHome && (
        <Card title="Prayers at the masjid" step="weekly" editing={editing} onEdit={setEditing}
          edit={<WeeklyStep initial={settings.weekly} masjidLabel={masjidLabel(settings)} onSaved={saved}
            onCancel={settings.missing.includes("weekly") ? undefined : cancel} />}>
          <ul className="plain">
            {settings.weekly.map((day) => {
              const names = PRAYERS.filter((p) => day[p]).map((p) => PRAYER_NAMES[p]);
              return (
                <li key={day.weekday}>
                  <strong>{WEEKDAYS[day.weekday]}:</strong> {names.length ? names.join(", ") : "all at home"}
                </li>
              );
            })}
          </ul>
        </Card>
      )}

      <Card title="Jumuah masjids" step="jumuah" editing={editing} onEdit={setEditing}
        edit={<JumuahStep settings={settings} onSaved={saved} onCancel={cancel} />}>
        {settings.jumuah_masjids.length === 0 ? (
          <p>None picked</p>
        ) : (
          <ul className="plain">
            {settings.jumuah_masjids.map((m) => (
              <li key={m.id}>
                {masjidName(m)} <span className="hint">· {m.iqamah_status}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <div className="actions">
        <button type="button" className="secondary" onClick={signOut} disabled={busy}>
          Sign out
        </button>
      </div>
    </main>
  );
}

type CardProps = {
  title: string;
  step: Step;
  editing: Step | null;
  onEdit: (step: Step) => void;
  edit: ReactNode;
  children: ReactNode;
};

function Card({ title, step, editing, onEdit, edit, children }: CardProps) {
  if (editing === step) return <div className="card">{edit}</div>;
  return (
    <section className="card setting" aria-label={title}>
      <div>
        <h2>{title}</h2>
        {children}
      </div>
      <button type="button" className="secondary small" onClick={() => onEdit(step)} disabled={editing !== null}
        aria-label={`Edit ${title.toLowerCase()}`}>
        Edit
      </button>
    </section>
  );
}
