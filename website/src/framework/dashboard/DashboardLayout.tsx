import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { ApiProvider } from "../lib/api";
import { ApiStatus } from "./ApiStatus";

export const PANELS = [
  { id: "advisor", label: "Advisor", blurb: "The format and protocol for your model, with the evidence behind them." },
  { id: "playground", label: "Playground", blurb: "Your tools in every format, side by side, with their token counts." },
  { id: "guard", label: "Guard", blurb: "Instructions hidden in tool descriptions, found and removed." },
  { id: "evidence", label: "Evidence", blurb: "The study's charts, each with its table." },
];

export function DashboardLayout({ panel, children }: { panel: string; children: ReactNode }) {
  const p = PANELS.find((x) => x.id === panel) ?? PANELS[0];
  return (
    <ApiProvider>
      <section className="fw-pagehead" style={{ paddingBottom: 0 }}>
        <div className="wrap">
          <div className="fw-dash-top">
            <div>
              <div className="label">
                <b>DASHBOARD</b> / {p.label.toUpperCase()}
              </div>
              <h1 style={{ fontSize: 36 }}>{p.label}</h1>
              <p style={{ marginBottom: 0 }}>{p.blurb}</p>
            </div>
            <ApiStatus />
          </div>
          <nav className="fw-dash-tabs" aria-label="Dashboard panels">
            {PANELS.map((x) => (
              <NavLink key={x.id} to={`/dashboard/${x.id}`} className={({ isActive }) => (isActive ? "active" : undefined)}>
                {x.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </section>
      <div className="wrap">{children}</div>
    </ApiProvider>
  );
}
