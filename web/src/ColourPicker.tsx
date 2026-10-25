// A dropdown of Google Calendar's event colours, each with its swatch and
// Google's name. A plain <select> can't show a coloured swatch in its
// options, so this is a small listbox: a button that opens a list.
// Keyboard: Enter, Space, or the arrow keys open it. Arrows move, Enter
// picks, Escape closes.

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { CALENDAR_COLOUR, GOOGLE_COLOURS } from "./labels";

type Props = {
  label: string;
  value: string | null;
  onChange: (id: string | null) => void;
};

// null first: the Prayers calendar's own colour.
const OPTIONS: { id: string | null; name: string; hex: string | null }[] = [
  { id: null, name: CALENDAR_COLOUR, hex: null },
  ...GOOGLE_COLOURS,
];

function Swatch({ hex }: { hex: string | null }) {
  return <span className={hex ? "swatch" : "swatch none"} style={hex ? { background: hex } : undefined} aria-hidden="true" />;
}

export function ColourPicker({ label, value, onChange }: Props) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const selected = Math.max(0, OPTIONS.findIndex((o) => o.id === value));
  const current = OPTIONS[selected];

  // Clicking anywhere else closes it.
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  useEffect(() => {
    if (open) list.current?.focus();
  }, [open]);

  function show() {
    setActive(selected);
    setOpen(true);
  }

  function pick(index: number) {
    onChange(OPTIONS[index].id);
    setOpen(false);
    button.current?.focus();
  }

  function onButtonKey(event: KeyboardEvent) {
    if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {
      event.preventDefault();
      show();
    }
  }

  function onListKey(event: KeyboardEvent) {
    if (event.key === "ArrowDown") setActive((i) => Math.min(OPTIONS.length - 1, i + 1));
    else if (event.key === "ArrowUp") setActive((i) => Math.max(0, i - 1));
    else if (event.key === "Home") setActive(0);
    else if (event.key === "End") setActive(OPTIONS.length - 1);
    else if (event.key === "Enter" || event.key === " ") pick(active);
    else if (event.key === "Escape" || event.key === "Tab") {
      setOpen(false);
      if (event.key === "Escape") button.current?.focus();
      return;
    } else return;
    event.preventDefault();
  }

  return (
    <div className="colour-picker" ref={box}>
      <span className="field-label" id={`${id}-label`}>
        {label}
      </span>
      <button
        ref={button}
        type="button"
        className="colour-button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-labelledby={`${id}-label ${id}-value`}
        onClick={() => (open ? setOpen(false) : show())}
        onKeyDown={onButtonKey}
      >
        <Swatch hex={current.hex} />
        <span id={`${id}-value`}>{current.name}</span>
        <span className="chevron" aria-hidden="true">
          ▾
        </span>
      </button>
      {open && (
        <ul
          ref={list}
          className="colour-list"
          role="listbox"
          tabIndex={-1}
          aria-labelledby={`${id}-label`}
          aria-activedescendant={`${id}-option-${active}`}
          onKeyDown={onListKey}
        >
          {OPTIONS.map((option, index) => (
            <li
              key={option.name}
              id={`${id}-option-${index}`}
              role="option"
              aria-selected={index === selected}
              className={index === active ? "active" : undefined}
              onMouseEnter={() => setActive(index)}
              onClick={() => pick(index)}
            >
              <Swatch hex={option.hex} />
              {option.name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
