// The Settings page, where returning users land: a button to open Google
// Calendar, then every saved setting on its own card, each with an Edit
// button. Edit opens the same step used in setup. Saving updates the calendar.

import { useEffect, useState, type ReactNode } from "react";
import { api, ApiError, SIGN_IN_URL } from "./api";
import { googleCalendarUrl } from "./googleCalendar";
import { asrName, colourName, earlyText, GOOGLE_COLOURS, masjidName, methodName, PRAYER_NAMES, PRAYERS, WEEKDAYS } from "./labels";
import { OsmFooter } from "./OsmFooter";
import { masjidLabel } from "./Setup";
import { JumuahStep } from "./steps/JumuahStep";
import { LocationStep } from "./steps/LocationStep";
import { MasjidStep } from "./steps/MasjidStep";
import { MethodsStep } from "./steps/MethodsStep";
import { OptionalStep } from "./steps/OptionalStep";
import { WeeklyStep } from "./steps/WeeklyStep";
import type { CalendarUpdate, Editable, SaveResponse, Settings } from "./types";

type Props = {
  email: string;
  initial: Settings;
  initialCalendar: CalendarUpdate | null;
  // The browser blocked the Google Calendar tab after setup.
  tabBlocked?: boolean;
  // Replaces Try again when finishing setup itself failed.
  onRetry?: () => void;
  onSignedOut: () => void;
};

export function SettingsPage({ email, initial, initialCalendar, tabBlocked = false, onRetry, onSignedOut }: Props) {
  const [settings, setSettings] = useState(initial);
  const [calendar, setCalendar] = useState(initialCalendar);

  // Setup's first update finishes after this page is already showing.
  useEffect(() => {
    setSettings(initial);
    setCalendar(initialCalendar);
  }, [initial, initialCalendar]);
  // A masjid picked after "I pray at home" still needs the weekly grid.
  const [editing, setEditing] = useState<Editable | null>(initial.missing[0] ?? null);
  const [busy, setBusy] = useState(false);

  function saved(response: SaveResponse) {
    setSettings(response.settings);
    setCalendar(response.calendar);
    setEditing(response.settings.missing[0] ?? null);
  }

  async function retry() {
    if (onRetry) return onRetry();
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
    <div className="page-with-footer">
      <main className="page">
        <header className="top">
          <h1>Settings</h1>
          <p className="hint">Signed in as {email}</p>
          <a className="button open-calendar" href={googleCalendarUrl(email)}>
            Open Google Calendar
          </a>
          {tabBlocked && (
            <p className="hint blocked-note">Your browser blocked the new tab, so open Google Calendar from here.</p>
          )}
        </header>

        {calendar && (
          <p className={calendar.status === "updated" || calendar.status === "adding" ? "notice" : "notice warning"} role="status">
            {calendar.message}{" "}
            {calendar.status === "waiting" && (
              <button type="button" className="link" onClick={retry} disabled={busy}>
                Try again
              </button>
            )}
            {calendar.status === "sign_in_needed" && <a href={SIGN_IN_URL}>Sign in again</a>}
          </p>
        )}

        <Card title="Location" step="address" editing={editing} onEdit={setEditing}
          edit={<LocationStep current={settings.place_name} onSaved={saved} onKeep={cancel} keepLabel="Cancel" />}>
          <p>{settings.place_name}</p>
          <p className="hint">Time zone: {settings.time_zone}</p>
        </Card>

        <Card title="Prayer time method" step="methods" editing={editing} onEdit={setEditing}
          edit={<MethodsStep initialMethod={settings.method} initialAsr={settings.asr_method} onSaved={saved} onCancel={cancel} />}>
          <p>{methodName(settings.method)}, {asrName(settings.asr_method)} Asr</p>
        </Card>

        <Card title="Main masjid" step="masjid" editing={editing} onEdit={setEditing}
          edit={<MasjidStep settings={settings} onSaved={saved} onCancel={cancel} skipLabel="I pray at home" />}>
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
            <ol className="plain">
              {settings.jumuah_masjids.map((m) => (
                <li key={m.id}>
                  {masjidName(m)} <span className="hint">· {m.iqamah_status}</span>
                </li>
              ))}
            </ol>
          )}
        </Card>

        <Card title="Extras" step="optional" editing={editing} onEdit={setEditing}
          edit={<OptionalStep settings={settings} onSaved={saved}
            onCancel={settings.missing.includes("optional") ? undefined : cancel} canSkip={settings.missing.includes("optional")} />}>
          <p>{earlyText(settings.arrive_early_minutes)}</p>
          <p>
            Prayer colour: <ColourName id={settings.prayer_color_id} />
          </p>
          <p>
            Drive colour: <ColourName id={settings.drive_color_id} />
          </p>
        </Card>

        <div className="actions">
          <button type="button" className="secondary" onClick={signOut} disabled={busy}>
            Sign out
          </button>
        </div>
      </main>
      <OsmFooter />
    </div>
  );
}

function ColourName({ id }: { id: string | null }) {
  const hex = GOOGLE_COLOURS.find((c) => c.id === id)?.hex;
  return (
    <span className="colour-name">
      <span className={hex ? "swatch" : "swatch none"} style={hex ? { background: hex } : undefined} aria-hidden="true" />
      {colourName(id)}
    </span>
  );
}

type CardProps = {
  title: string;
  step: Editable;
  editing: Editable | null;
  onEdit: (step: Editable) => void;
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
