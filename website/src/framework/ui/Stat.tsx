import type { ReactNode } from "react";

export function Stat({ value, unit, label }: { value: ReactNode; unit?: string; label: ReactNode }) {
  return (
    <div className="fw-stat">
      <div className="v">
        {value}
        {unit && <small>{unit}</small>}
      </div>
      <div className="k">{label}</div>
    </div>
  );
}
