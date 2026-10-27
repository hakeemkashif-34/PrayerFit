// A short number box with "minutes" after it, an optional hint, and its error
// under it. Used for both "how early" boxes and both notification boxes, on
// setup and Settings. inputMode="numeric" opens the number keypad on phones.

type Props = {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  error: string;
  min: number;
  max: number;
  // A short line under the box, like "0 = no notification".
  hint?: string;
};

export function MinutesField({ id, label, value, onChange, error, min, max, hint }: Props) {
  const errorId = `${id}-error`;
  const hintId = `${id}-hint`;
  // Screen readers read the hint, and the error when there is one, after the box's label.
  const describedBy = [hint ? hintId : "", error ? errorId : ""].filter(Boolean).join(" ") || undefined;

  return (
    <>
      {/* On Settings, the question and the box share a line when they fit. */}
      <div className="inline-field">
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
            aria-describedby={describedBy}
          />
          <span aria-hidden="true">minutes</span>
        </div>
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
