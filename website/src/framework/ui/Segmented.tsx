import { useRef, type KeyboardEvent } from "react";

/* A radio group drawn as a segmented control. Arrow keys move the choice. */

export function Segmented<T extends string | number>({
  options,
  value,
  onChange,
  label,
  titles,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
  titles?: Partial<Record<string, string>>;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const idx = Math.max(0, options.findIndex((o) => o.value === value));
  const onKey = (e: KeyboardEvent) => {
    let n = idx;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") n = (idx + 1) % options.length;
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") n = (idx - 1 + options.length) % options.length;
    else return;
    e.preventDefault();
    onChange(options[n].value);
    refs.current[n]?.focus();
  };
  return (
    <div className="fw-seg" role="radiogroup" aria-label={label} onKeyDown={onKey}>
      {options.map((o, i) => (
        <button
          key={String(o.value)}
          ref={(el) => (refs.current[i] = el)}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          tabIndex={o.value === value ? 0 : -1}
          title={titles?.[String(o.value)]}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
