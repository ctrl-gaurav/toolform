import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";

/* Tabs with the ARIA tab pattern: arrow keys, Home and End move between tabs. */

export interface TabItem {
  id: string;
  label: ReactNode;
  panel: ReactNode;
}

export function Tabs({ items, value, onChange, label }: { items: TabItem[]; value: string; onChange: (id: string) => void; label: string }) {
  const base = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const idx = Math.max(0, items.findIndex((t) => t.id === value));
  const move = (e: KeyboardEvent) => {
    let next = idx;
    if (e.key === "ArrowRight") next = (idx + 1) % items.length;
    else if (e.key === "ArrowLeft") next = (idx - 1 + items.length) % items.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = items.length - 1;
    else return;
    e.preventDefault();
    onChange(items[next].id);
    refs.current[next]?.focus();
  };
  return (
    <div className="fw-tabs">
      <div role="tablist" aria-label={label} onKeyDown={move}>
        {items.map((t, i) => (
          <button
            key={t.id}
            ref={(el) => (refs.current[i] = el)}
            role="tab"
            type="button"
            id={`${base}-tab-${t.id}`}
            aria-selected={i === idx}
            aria-controls={`${base}-panel-${t.id}`}
            tabIndex={i === idx ? 0 : -1}
            onClick={() => onChange(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`${base}-panel-${items[idx].id}`} aria-labelledby={`${base}-tab-${items[idx].id}`}>
        {items[idx].panel}
      </div>
    </div>
  );
}
