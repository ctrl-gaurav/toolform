import { Link } from "react-router-dom";
import type { EvidenceRow } from "../lib/advisor";

/* Which explorer chart shows each source table. */
export const CHART_FOR_SOURCE: Record<string, string> = {
  "paper:tab_models_main": "families",
  "paper:tab_main": "graders",
  "paper:tab_count_by_format": "tool-count",
  "paper:tab_count": "tool-count",
  "paper:tab_protocol": "crossing",
  "paper:tab_cost": "cost",
  "paper:tab_disclosure_v2": "disclosure",
  "paper:tab_pressure": "injection",
  "paper:tab_injection_trust": "injection",
  "paper:tab_ladder": "ladder",
  "paper:tab_selection": "selection",
  "export:format_leaderboard": "cost",
};

export function fmtValue(r: EvidenceRow): string {
  if (r.value === null || r.value === undefined) return "n/a";
  const v = r.unit === "%" ? `${r.value.toFixed(2)}%` : `${r.value.toLocaleString("en-US")} ${r.unit}`;
  return r.interval ? `${v} [${r.interval[0].toFixed(2)}, ${r.interval[1].toFixed(2)}]` : v;
}

export function EvidenceList({ rows, title }: { rows: EvidenceRow[]; title?: string }) {
  if (!rows.length) return null;
  return (
    <div>
      {title && <h3 style={{ fontSize: 15 }}>{title}</h3>}
      <ul className="fw-list-plain" style={{ gap: 0 }}>
        {rows.map((r, i) => {
          const chart = CHART_FOR_SOURCE[r.source];
          const src = r.source.replace(/^paper:/, "").replace(/^export:/, "site export: ");
          return (
            <li key={i} className="fw-evrow">
              <div>
                <div>{r.label}</div>
                <div className="src">
                  {chart ? <Link to={`/dashboard/evidence?chart=${chart}`}>{src}</Link> : src}
                  {r.note ? ` · ${r.note}` : ""}
                </div>
              </div>
              <div className="val">{fmtValue(r)}</div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
