// The small editors on the Settings page's Optional section. Each one
// changes one thing and saves it on its own.
//
// PUT /settings/optional takes every optional answer at once, so the
// editors that use it send the saved answers with just their one change.

import { useState, type FormEvent, type ReactNode } from "react";
import { api, ApiError } from "./api";
import { ColourPicker } from "./ColourPicker";
import { JumuahChooser } from "./JumuahChooser";
import { EARLY_ERROR, MAX_EARLY, wholeMinutes } from "./labels";
import { MinutesField } from "./MinutesField";
import type { OptionalAnswers, SaveResponse, Settings, SlotKey } from "./types";

type EditorProps = {
  settings: Settings;
  onSaved: (response: SaveResponse) => void;
  onCancel: () => void;
};

function saved(settings: Settings): OptionalAnswers {
  return {
    arrive_early_minutes: settings.arrive_early_minutes,
    jumuah_arrive_early_minutes: settings.jumuah_arrive_early_minutes,
    short_name: settings.main_masjid_short_name ?? undefined,
    prayer_color_id: settings.prayer_color_id,
    drive_color_id: settings.drive_color_id,
  };
}

// A form with Save and Cancel, and the error from a failed save.
function EditorForm({ title, onSave, onCancel, children }: {
  title: string;
  // Returns the save, or null when the form found a problem and showed it.
  onSave: () => Promise<unknown> | null;
  onCancel: () => void;
  children: ReactNode;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const id = `edit-${title.toLowerCase().replace(/\W+/g, "-")}`;

  async function submit(event: FormEvent) {
    event.preventDefault();
    const save = onSave();
    if (save === null) return;
    setBusy(true);
    setError("");
    try {
      await save;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save. Try again.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} aria-labelledby={id} noValidate>
      <h3 id={id}>{title}</h3>
      {children}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="actions">
        <button type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save"}
        </button>
        <button type="button" className="secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export function ShortNameEditor({ settings, onSaved, onCancel }: EditorProps) {
  const [name, setName] = useState(settings.main_masjid_short_name ?? "");
  const masjid = settings.main_masjid;
  return (
    <EditorForm title="Short name" onCancel={onCancel}
      onSave={() => api.saveOptional({ ...saved(settings), short_name: name.trim() || undefined }).then(onSaved)}>
      <label htmlFor="short-name">Short name for {masjid?.name ?? "your masjid"}</label>
      <input id="short-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="KMA" maxLength={40} />
      <p className="hint small-line">Events will say "Dhuhr at {name.trim() || masjid?.name || "your masjid"}".</p>
    </EditorForm>
  );
}

export function EarlyEditor({ settings, onSaved, onCancel, jumuah }: EditorProps & { jumuah: boolean }) {
  const current = jumuah ? settings.jumuah_arrive_early_minutes : settings.arrive_early_minutes;
  const [text, setText] = useState(String(current));
  const [error, setError] = useState("");
  const field = jumuah ? "jumuah_arrive_early_minutes" : "arrive_early_minutes";

  function save() {
    const minutes = wholeMinutes(text, 0, MAX_EARLY);
    setError(minutes === null ? EARLY_ERROR : "");
    if (minutes === null) return null;
    return api.saveOptional({ ...saved(settings), [field]: minutes }).then(onSaved);
  }

  return (
    <EditorForm title={jumuah ? "How early for Jumuah" : "How early for prayers"} onSave={save} onCancel={onCancel}>
      <MinutesField id={jumuah ? "jumuah-early" : "arrive-early"}
        label={jumuah ? "How early do you want to arrive before Jumuah (Friday prayer)?" : "How early do you want to arrive before iqamah (daily prayers)?"}
        value={text} onChange={setText} error={error} min={0} max={MAX_EARLY} />
    </EditorForm>
  );
}

export function ColourEditor({ settings, onSaved, onCancel, drive }: EditorProps & { drive: boolean }) {
  const [colour, setColour] = useState(drive ? settings.drive_color_id : settings.prayer_color_id);
  const title = drive ? "Drive colour" : "Prayer colour";
  const field = drive ? "drive_color_id" : "prayer_color_id";
  return (
    <EditorForm title={title} onCancel={onCancel}
      onSave={() => api.saveOptional({ ...saved(settings), [field]: colour }).then(onSaved)}>
      <ColourPicker label={title} value={colour} onChange={setColour} />
    </EditorForm>
  );
}

export function JumuahPickEditor({ settings, onSaved, onCancel }: EditorProps) {
  const [pick, setPick] = useState<SlotKey | null>(settings.jumuah_pick);
  return (
    <EditorForm title="Jumuah pick" onCancel={onCancel} onSave={() => api.saveJumuahPick(pick).then(onSaved)}>
      <JumuahChooser selected={pick} onSelect={setPick} heading="h4" where="settings" />
    </EditorForm>
  );
}
