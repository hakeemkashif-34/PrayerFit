// The Settings page, where returning users land: a button to open Google
// Calendar, then one card with 2 sections. "Required" has the setup
// questions (location, masjid, weekly prayers). "Optional" has everything
// with a default. Each item has its own Edit button and saves on its own.
// Saving updates the calendar.

import { useEffect, useState, type ReactNode } from "react";
import { api, ApiError, SIGN_IN_URL } from "./api";
import { BusyBanner } from "./BusyBanner";
import { googleCalendarUrl } from "./googleCalendar";
import {
  colourName, earlyText, GOOGLE_COLOURS, jumuahEarlyText, masjidLabel, masjidName, PRAYER_NAMES, PRAYERS, WEEKDAYS,
} from "./labels";
import { OsmFooter } from "./OsmFooter";
import { ColourEditor, CommuteTimesEditor, EarlyEditor, JumuahPickEditor, ShortNameEditor } from "./SettingsEditors";
import { JumuahStep } from "./steps/JumuahStep";
import { LocationStep } from "./steps/LocationStep";
import { MasjidStep } from "./steps/MasjidStep";
import { WeeklyStep } from "./steps/WeeklyStep";
import type { CalendarUpdate, Editable, SaveResponse, Settings } from "./types";

type Props = {
  email: string;
  // False until the user signs in again with free/busy access.
  busyAccess: boolean;
  initial: Settings;
  initialCalendar: CalendarUpdate | null;
  // The browser blocked the Google Calendar tab after setup.
  tabBlocked?: boolean;
  // Replaces Try again when finishing setup itself failed.
  onRetry?: () => void;
  onSignedOut: () => void;
};

export function SettingsPage({ email, busyAccess, initial, initialCalendar, tabBlocked = false, onRetry, onSignedOut }: Props) {
  const [settings, setSettings] = useState(initial);
  const [calendar, setCalendar] = useState(initialCalendar);

  // Setup's first update finishes after this page is already showing.
  useEffect(() => {
    setSettings(initial);
    setCalendar(initialCalendar);
  }, [initial, initialCalendar]);
  // A masjid picked after "I pray at home" still needs the weekly grid.
  const [editing, setEditing] = useState<Editable | null>(firstMissing(initial));
  const [busy, setBusy] = useState(false);

  function saved(response: SaveResponse) {
    setSettings(response.settings);
    setCalendar(response.calendar);
    setEditing(firstMissing(response.settings));
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
  const rows = { editing, onEdit: setEditing };

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

        {!busyAccess && <BusyBanner />}

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

        <div className="card settings-card">
          <section aria-labelledby="required-title">
            <h2 id="required-title" className="section-title">Required</h2>
            <Row title="Location" step="address" {...rows}
              edit={<LocationStep current={settings.place_name} onSaved={saved} onKeep={cancel} keepLabel="Cancel" />}>
              <p>{settings.place_name}</p>
              <p className="hint">Time zone: {settings.time_zone}</p>
            </Row>

            <Row title="Main masjid" step="masjid" {...rows}
              edit={<MasjidStep settings={settings} onSaved={saved} onCancel={cancel} skipLabel="I pray at home" />}>
              {atHome || !settings.main_masjid ? (
                <p>I pray at home</p>
              ) : (
                <>
                  <p>{masjidName(settings.main_masjid)}</p>
                  <p className="hint">{settings.main_masjid.iqamah_status}</p>
                </>
              )}
            </Row>

            {!atHome && (
              <Row title="Prayers at the masjid" step="weekly" {...rows}
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
              </Row>
            )}
          </section>

          <section aria-labelledby="optional-section-title">
            <h2 id="optional-section-title" className="section-title">Optional</h2>
            <Row title="Jumuah masjids" step="jumuah" {...rows}
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
            </Row>

            {settings.jumuah_masjids.length > 0 && (
              <Row title="Jumuah pick" step="jumuah_pick" {...rows}
                edit={<JumuahPickEditor settings={settings} onSaved={saved} onCancel={cancel} />}>
                <p>{pickText(settings)}</p>
              </Row>
            )}

            {!atHome && settings.main_masjid && (
              <Row title="Short name" step="short_name" {...rows}
                edit={<ShortNameEditor settings={settings} onSaved={saved} onCancel={cancel} />}>
                <p>{settings.main_masjid_short_name ?? "None"}</p>
              </Row>
            )}

            <Row title="How early for prayers" step="early" {...rows}
              edit={<EarlyEditor settings={settings} onSaved={saved} onCancel={cancel} jumuah={false} />}>
              <p>{earlyText(settings.arrive_early_minutes)}</p>
            </Row>

            {settings.jumuah_masjids.length > 0 && (
              <Row title="How early for Jumuah" step="jumuah_early" {...rows}
                edit={<EarlyEditor settings={settings} onSaved={saved} onCancel={cancel} jumuah />}>
                <p>{jumuahEarlyText(settings.jumuah_arrive_early_minutes)}</p>
              </Row>
            )}

            {settings.commute_times.length > 0 && (
              <Row title="Commute times" step="commute" {...rows}
                edit={<CommuteTimesEditor settings={settings} onSaved={saved} onCancel={cancel} />}>
                <ul className="plain">
                  {settings.commute_times.map((c) => (
                    <li key={c.masjid_id}>
                      <strong>{c.masjid_name}:</strong>{" "}
                      {c.minutes === null ? "driving estimate from OpenRouteService" : `${c.minutes} min (your time)`}
                    </li>
                  ))}
                </ul>
              </Row>
            )}

            <Row title="Prayer colour" step="prayer_colour" {...rows}
              edit={<ColourEditor settings={settings} onSaved={saved} onCancel={cancel} commute={false} />}>
              <p><ColourName id={settings.prayer_color_id} /></p>
            </Row>

            <Row title="Commute colour" step="commute_colour" {...rows}
              edit={<ColourEditor settings={settings} onSaved={saved} onCancel={cancel} commute />}>
              <p><ColourName id={settings.drive_color_id} /></p>
            </Row>
          </section>
        </div>

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

// A required question left unanswered (like the grid, after picking a masjid
// instead of "I pray at home") opens straight away.
function firstMissing(settings: Settings): Editable | null {
  const step = settings.missing[0];
  return step === "address" || step === "masjid" || step === "weekly" ? step : null;
}

function pickText(settings: Settings): string {
  const pick = settings.jumuah_pick;
  const masjid = pick && settings.jumuah_masjids.find((m) => m.id === pick.masjid_id);
  if (!pick || !masjid) return "The earliest Jumuah that fits your calendar";
  const order = ["1st", "2nd", "3rd"][pick.order - 1] ?? `${pick.order}th`;
  return `${order} Jumuah at ${masjidName(masjid)}, if it fits your calendar`;
}

type RowProps = {
  title: string;
  step: Editable;
  editing: Editable | null;
  onEdit: (step: Editable) => void;
  edit: ReactNode;
  children: ReactNode;
};

// One setting: its name and value with an Edit button, or its editor.
function Row({ title, step, editing, onEdit, edit, children }: RowProps) {
  if (editing === step) return <div className="setting-row editing">{edit}</div>;
  return (
    <section className="setting-row" aria-label={title}>
      <div>
        <h3>{title}</h3>
        {children}
      </div>
      <button type="button" className="secondary small" onClick={() => onEdit(step)} disabled={editing !== null}
        aria-label={`Edit ${title.toLowerCase()}`}>
        Edit
      </button>
    </section>
  );
}
