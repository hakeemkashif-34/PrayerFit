// The Settings page, where returning users land: a button to open Google
// Calendar, then 2 cards, side by side on a computer. "Required" has the setup
// questions (location, masjid, weekly prayers, Jumuah pick). "Optional" has everything
// with a default. Each item shows its setup question as the label and just the
// answer as the value, with its own Edit button, and saves on its own.
// Saving updates the calendar. Jumuah is always at the main masjid.

import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, SIGN_IN_URL } from "./api";
import { BusyBanner } from "./BusyBanner";
import { googleCalendarUrl } from "./googleCalendar";
import {
  colourName, GOOGLE_COLOURS, masjidLabel, masjidName, minutesText, PRAYER_NAMES, PRAYERS, QUESTIONS, WEEKDAYS,
} from "./labels";
import { OsmFooter } from "./OsmFooter";
import { QUESTION as JUMUAH_QUESTION } from "./JumuahChooser";
import { ColourEditor, EarlyEditor, JumuahPickEditor, ShortNameEditor } from "./SettingsEditors";
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
  // After "Delete my account". False: Google couldn't be reached.
  onDeleted: (googleCleaned: boolean) => void;
};

export function SettingsPage({ email, busyAccess, initial, initialCalendar, tabBlocked = false, onRetry, onSignedOut, onDeleted }: Props) {
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
  // Jumuah is always at the main masjid. Praying at home means no Jumuah.
  const hasJumuah = !atHome && settings.main_masjid !== null;
  const rows = { editing, onEdit: setEditing };

  return (
    <div className="page-with-footer">
      <main className="page settings-page">
        <header className="top">
          <div>
            <h1>Settings</h1>
            <p className="hint">Signed in as {email}</p>
            <p className="hint"><mark className="highlight">Updates and changes</mark> are reflected on your calendar every 5 minutes.</p>
          </div>
          <div className="top-action">
            <a className="button open-calendar" href={googleCalendarUrl(email)}>
              Open Google Calendar
            </a>
            {tabBlocked && (
              <p className="hint blocked-note">Your browser blocked the new tab, so open Google Calendar from here.</p>
            )}
          </div>
        </header>

        {settings.masjid_notices.map((text) => (
          <p key={text} className="notice warning" role="status">{text}</p>
        ))}

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

        <div className="settings-grid">
          <section className="card settings-card required" aria-labelledby="required-title">
            <h2 id="required-title" className="section-title">Required</h2>
            <Row title="Location" question={QUESTIONS.location} step="address" {...rows}
              edit={<LocationStep current={settings.place_name} onSaved={saved} onKeep={cancel} keepLabel="Cancel" />}>
              <p>{settings.place_name}</p>
              <p className="hint">Time zone: {settings.time_zone}</p>
            </Row>

            <Row title="Main masjid" question={QUESTIONS.masjid} step="masjid" {...rows}
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
              <Row title="Prayers at the masjid" question={QUESTIONS.weekly} step="weekly" {...rows}
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

            {hasJumuah && (
              <Row title="Jumuah pick" question={JUMUAH_QUESTION} step="jumuah_pick" {...rows}
                edit={<JumuahPickEditor settings={settings} onSaved={saved} onCancel={cancel} />}>
                <p>{pickText(settings)}</p>
              </Row>
            )}
          </section>

          <section className="card settings-card optional" aria-labelledby="optional-section-title">
            <h2 id="optional-section-title" className="section-title">Optional</h2>
            {!atHome && settings.main_masjid && (
              <Row title="Short name" step="short_name" {...rows}
                edit={<ShortNameEditor settings={settings} onSaved={saved} onCancel={cancel} />}>
                <p>{settings.main_masjid_short_name ?? "None"}</p>
              </Row>
            )}

            <Row title="How early for prayers" question={QUESTIONS.early} step="early" {...rows}
              edit={<EarlyEditor settings={settings} onSaved={saved} onCancel={cancel} jumuah={false} />}>
              <p>{minutesText(settings.arrive_early_minutes)}</p>
            </Row>

            {hasJumuah && (
              <Row title="How early for Jumuah" question={QUESTIONS.jumuahEarly} step="jumuah_early" {...rows}
                edit={<EarlyEditor settings={settings} onSaved={saved} onCancel={cancel} jumuah />}>
                <p>{minutesText(settings.jumuah_arrive_early_minutes)}</p>
              </Row>
            )}

            <Row title="Prayer colour" step="prayer_colour" {...rows}
              edit={<ColourEditor settings={settings} onSaved={saved} onCancel={cancel} drive={false} />}>
              <p><ColourName id={settings.prayer_color_id} /></p>
            </Row>

            <Row title="Drive colour" step="drive_colour" {...rows}
              edit={<ColourEditor settings={settings} onSaved={saved} onCancel={cancel} drive />}>
              <p><ColourName id={settings.drive_color_id} /></p>
            </Row>
          </section>
        </div>

        <div className="actions">
          <button type="button" className="secondary" onClick={signOut} disabled={busy}>
            Sign out
          </button>
        </div>

        <DeleteAccount onDeleted={onDeleted} />
      </main>
      <OsmFooter />
    </div>
  );
}

export const DELETE_WARNING =
  "This deletes your PrayerFit account, your settings, and the Prayers calendar from your Google Calendar. This can't be undone.";

// At the very bottom, with a red outline so it looks careful, not inviting.
// It asks first, with Cancel focused, so a stray Enter doesn't delete anything.
function DeleteAccount({ onDeleted }: { onDeleted: (googleCleaned: boolean) => void }) {
  const [asking, setAsking] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");

  async function confirm() {
    setDeleting(true);
    setError("");
    try {
      const answer = await api.deleteAccount();
      onDeleted(answer.google_cleaned);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't delete your account. Try again.");
      setDeleting(false);
    }
  }

  if (!asking) {
    return (
      <div className="delete-account">
        <button type="button" className="danger-outline" onClick={() => setAsking(true)}>
          Delete my account
        </button>
      </div>
    );
  }
  return (
    <section className="delete-account confirm" role="alertdialog" aria-labelledby="delete-title" aria-describedby="delete-text">
      <h2 id="delete-title">Delete my account?</h2>
      <p id="delete-text">{DELETE_WARNING}</p>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="actions">
        <button type="button" className="danger" onClick={() => void confirm()} disabled={deleting}>
          {deleting ? "Deleting…" : "Delete my account"}
        </button>
        <button type="button" className="secondary" autoFocus onClick={() => setAsking(false)} disabled={deleting}>
          Cancel
        </button>
      </div>
    </section>
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

// Just the answer: the question already says it's about Jumuah at the main masjid.
function pickText(settings: Settings): string {
  const pick = settings.jumuah_pick;
  if (!pick || pick.masjid_id !== settings.main_masjid?.id) return "The earliest Jumuah that fits your calendar";
  return `${["1st", "2nd", "3rd"][pick.order - 1] ?? `${pick.order}th`} Jumuah`;
}

type RowProps = {
  // A short name, for screen readers and the Edit button, like "How early for prayers".
  title: string;
  // What's shown as the label: the setup question when there is one. Otherwise the title.
  question?: string;
  step: Editable;
  editing: Editable | null;
  onEdit: (step: Editable) => void;
  edit: ReactNode;
  children: ReactNode;
};

// One setting: its name (small and muted) over its value (larger and darker)
// with an Edit button, or its editor in the same place. Switching between the
// two eases the row's height from old to new, so it opens and closes smoothly
// instead of jumping. Skipped when the device asks for less motion.
function Row({ title, question, step, editing, onEdit, edit, children }: RowProps) {
  const open = editing === step;
  const row = useRef<HTMLElement>(null);
  const height = useRef(0);
  // Only rows the user has opened or closed get the fade, not every row on page load.
  const [moved, setMoved] = useState(false);
  const wasOpen = useRef(open);

  // Keep the last height up to date, so a switch knows where it started from.
  useEffect(() => {
    const el = row.current;
    if (!el) return;
    height.current = el.offsetHeight;
    const watch = new ResizeObserver(() => (height.current = el.offsetHeight));
    watch.observe(el);
    return () => watch.disconnect();
  }, []);

  useLayoutEffect(() => {
    if (wasOpen.current === open) return;
    wasOpen.current = open;
    setMoved(true);
    const el = row.current;
    const from = height.current;
    if (!el || !from || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const to = el.offsetHeight;
    if (from === to) return;
    el.style.overflow = "hidden";
    const ease = el.animate([{ height: `${from}px` }, { height: `${to}px` }], { duration: 220, easing: "ease-out" });
    ease.onfinish = ease.oncancel = () => (el.style.overflow = "");
  }, [open]);

  return (
    <section ref={row} className={`setting-row${open ? " open" : ""}${moved ? " moved" : ""}`} aria-label={title}>
      {open ? (
        <div className="row-edit">{edit}</div>
      ) : (
        <div className="row-view">
          <div className="row-text">
            <h3>{question ?? title}</h3>
            <div className="row-value">{children}</div>
          </div>
          <button type="button" className="secondary small" onClick={() => onEdit(step)} disabled={editing !== null}
            aria-label={`Edit ${title.toLowerCase()}`}>
            Edit
          </button>
        </div>
      )}
    </section>
  );
}
