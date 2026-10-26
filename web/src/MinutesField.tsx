// A short number box with "minutes" after it, and its error under it.
// Used for both "how early" boxes.

type Props = {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  error: string;
  min: number;
  max: number;
};

export function MinutesField({ id, label, value, onChange, error, min, max }: Props) {
  const errorId = `${id}-error`;

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
          aria-describedby={error ? errorId : undefined}
        />
        <span aria-hidden="true">minutes</span>
      </div>
      {error && (
        <p className="error field-error" id={errorId} role="alert">
          {error}
        </p>
      )}
    </>
  );
}
