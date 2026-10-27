// A notification dropdown: No notification, or 5 to 30 minutes before. It
// becomes a Google Calendar popup. Setup's optional page and Settings both use it,
// so the labels, choices, and defaults are always the same.

import { REMINDER_CHOICES, reminderText } from "./labels";
import type { ReminderMinutes } from "./types";

type Props = {
  id: string;
  label: string;
  value: ReminderMinutes | null;
  onChange: (value: ReminderMinutes | null) => void;
};

export function ReminderField({ id, label, value, onChange }: Props) {
  return (
    // On Settings, the label and the dropdown share a line when they fit. Setup stacks them.
    <div className="inline-field">
      <label htmlFor={id}>{label}</label>
      <select id={id} className="reminder-select" value={value ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? null : (Number(e.target.value) as ReminderMinutes))}>
        {REMINDER_CHOICES.map((choice) => (
          <option key={choice ?? "none"} value={choice ?? ""}>{reminderText(choice)}</option>
        ))}
      </select>
    </div>
  );
}
