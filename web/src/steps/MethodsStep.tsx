// Calculation method and Asr method. Only on the settings page for now.

import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { ASR_METHODS, METHODS } from "../labels";
import type { SaveResponse } from "../types";

type Props = {
  initialMethod: string | null;
  initialAsr: string | null;
  onSaved: (response: SaveResponse) => void;
  onCancel?: () => void;
};

export function MethodsStep({ initialMethod, initialAsr, onSaved, onCancel }: Props) {
  const [method, setMethod] = useState(initialMethod ?? "isna");
  const [asr, setAsr] = useState(initialAsr ?? "standard");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onSaved(await api.saveMethods(method, asr));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save. Try again.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} aria-labelledby="methods-title">
      <h2 id="methods-title">How to work out prayer times</h2>
      <fieldset>
        <legend>Calculation method</legend>
        <p className="hint">Scholars differ on how dark the sky must be for Fajr and Isha.</p>
        {METHODS.map((m) => (
          <label key={m.value} className="choice">
            <input type="radio" name="method" value={m.value} checked={method === m.value} onChange={() => setMethod(m.value)} />
            <span>
              <strong>{m.name}</strong>
              <small>{m.about}</small>
            </span>
          </label>
        ))}
      </fieldset>
      <fieldset>
        <legend>Asr method</legend>
        {ASR_METHODS.map((m) => (
          <label key={m.value} className="choice">
            <input type="radio" name="asr" value={m.value} checked={asr === m.value} onChange={() => setAsr(m.value)} />
            <span>
              <strong>{m.name}</strong>
              <small>{m.about}</small>
            </span>
          </label>
        ))}
      </fieldset>
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
