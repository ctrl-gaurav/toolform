import { useState, type ReactNode } from "react";
import { evidenceUrl } from "../lib/evidence";

/* Every chart: a title that states the finding, a caption with the source
 * table and conditions, a table view, and the JSON it was drawn from. */
export function ChartFrame({
  id,
  title,
  caption,
  file,
  ariaLabel,
  controls,
  table,
  children,
}: {
  id: string;
  title: string;
  caption: ReactNode;
  file: string;
  ariaLabel: string;
  controls?: ReactNode;
  table: ReactNode;
  children: ReactNode;
}) {
  const [asTable, setAsTable] = useState(false);
  return (
    <figure className="fw-card fw-chart" id={`chart-${id}`} style={{ margin: 0, scrollMarginTop: 80 }} aria-labelledby={`chart-${id}-t`}>
      <header>
        <div>
          <div className="label">
            <b>{file.replace(".json", "")}</b>
          </div>
          <h3 id={`chart-${id}-t`}>{title}</h3>
        </div>
        <div className="row" style={{ gap: 6 }}>
          {controls}
          <button type="button" className="fw-btn small" aria-pressed={asTable} onClick={() => setAsTable((t) => !t)}>
            {asTable ? "Show as chart" : "Show as table"}
          </button>
          <a className="fw-btn small ghost" href={evidenceUrl(file.replace(".json", ""))} download={file}>
            Download JSON
          </a>
        </div>
      </header>
      {asTable ? (
        <div className="tablewrap">{table}</div>
      ) : (
        <div className="plotbox" role="img" aria-label={ariaLabel}>
          {children}
        </div>
      )}
      <figcaption>{caption}</figcaption>
    </figure>
  );
}

export function Legend({ items }: { items: { label: string; color: string; shape?: "dot" | "line" }[] }) {
  return (
    <div className="fw-legend" aria-hidden="true">
      {items.map((i) => (
        <span key={i.label}>
          <span
            className="fw-swatch"
            style={{ background: i.color, height: i.shape === "line" ? 3 : 10, borderRadius: i.shape === "dot" ? "50%" : 2 }}
          />
          {i.label}
        </span>
      ))}
    </div>
  );
}

export function TooltipBox({ title, rows }: { title: string; rows: [string, string][] }) {
  return (
    <div className="fw-tooltip">
      <div className="t">{title}</div>
      {rows.map(([k, v]) => (
        <div className="r" key={k}>
          <span>{k}</span>
          <span>{v}</span>
        </div>
      ))}
    </div>
  );
}

export const pct = (v: number | null | undefined, d = 2) => (v === null || v === undefined ? "n/a" : `${v.toFixed(d)}%`);
