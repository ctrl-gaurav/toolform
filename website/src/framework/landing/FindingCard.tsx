import type { ReactNode } from "react";
import { Link } from "react-router-dom";

export function FindingCard({ value, unit, children, source, chart, to, wide, extra, cta = "open the chart" }: { value: ReactNode; unit?: string; children: ReactNode; source: string; chart?: string; to?: string; wide?: boolean; extra?: ReactNode; cta?: string }) {
  return (
    <Link to={to ?? `/dashboard/evidence?chart=${chart}`} className={`fw-card fw-finding${wide ? " wide" : ""}`}>
      <div style={wide ? { flex: "1 1 320px", display: "grid", gap: 10 } : { display: "contents" }}>
        <div className="v">
          {value}
          {unit && <small>{unit}</small>}
        </div>
        <p>{children}</p>
        <span className="src">{source} · {cta}</span>
      </div>
      {extra}
    </Link>
  );
}
