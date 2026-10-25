// A short number box with "minutes" after it, and its error under it.
// Used for both "how early" boxes and the commute times.

type Props = {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  error: string;
  min: number;
  max: number;
  hint?: string;
};

export function MinutesField({ id, label, value, onChange, error, min, max, hint }: Props) {
  const errorId = `${id}-error`;
  const hintId = `${id}-hint`;
  const described = [hint ? hintId : "", error ? errorId : ""].filter(Boolean).join(" ") || undefined;
  return (
    <>
      <label htmlFor={id}>{label}</label>
      <div className="minutes-field">
        <input
          id={id}
          type="number"
          inputMode="numeric"
          min={min}
          max={max}
          step={1}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={error ? true : undefined}
          aria-describedby={described}
        />
        <span aria-hidden="true">minutes</span>
      </div>
      {hint && (
        <p className="hint small-line" id={hintId}>
          {hint}
        </p>
      )}
      {error && (
        <p className="error field-error" id={errorId} role="alert">
          {error}
        </p>
      )}
    </>
  );
}
