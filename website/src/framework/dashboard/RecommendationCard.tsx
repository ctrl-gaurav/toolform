import { Link } from "react-router-dom";
import { fmtPct, type Recommendation } from "../lib/advisor";
import { cliFor, pythonFor } from "../lib/snippets";
import { CORE_FORMAT_LABELS, isCoreFormat } from "../lib/render";
import { fmtColor } from "../charts/palette";
import { Badge } from "../ui/Badge";
import { CopyButton } from "../ui/CopyButton";
import { EvidenceList } from "./EvidenceList";

export interface FormatBar {
  format_id: string;
  protocol_id: string;
  expected: number;
  interval: [number, number] | null;
}

function label(f: string) {
  return isCoreFormat(f) ? CORE_FORMAT_LABELS[f] : f;
}

function Range({ value, lo, hi }: { value: number; lo: number; hi: number }) {
  return (
    <div className="fw-range" role="img" aria-label={`Expected ${value.toFixed(2)}%, range ${lo.toFixed(2)} to ${hi.toFixed(2)} across the table values it rests on, on a scale of 0 to 100`}>
      <div className="track" />
      <div className="span" style={{ left: `${lo}%`, width: `${Math.max(0.6, hi - lo)}%` }} />
      <div className="pt" style={{ left: `${value}%` }} />
      <div className="ticks" aria-hidden="true">
        <span>0</span>
        <span>25</span>
        <span>50</span>
        <span>75</span>
        <span>100</span>
      </div>
    </div>
  );
}

/* The eight core formats' expected accuracy as horizontal bars, the winner
 * outlined, each bar's range drawn as a thin line. */
export function FormatBars({ bars, winner }: { bars: FormatBar[]; winner: string }) {
  const sorted = [...bars].sort((a, b) => b.expected - a.expected);
  return (
    <figure style={{ margin: 0 }}>
      <div className="fw-hbars" role="list" aria-label="Expected accuracy of the eight core formats for this situation">
        {sorted.map((b) => (
          <div key={b.format_id} role="listitem" className={`fw-hbar${b.format_id === winner ? " win" : ""}`}>
            <span className="name">
              <span className="fw-swatch" style={{ background: fmtColor(b.format_id) }} aria-hidden="true" />
              {label(b.format_id)}
            </span>
            <span className="plot" aria-hidden="true">
              <span className="fw-hbar-bar" style={{ width: `${b.expected}%`, background: fmtColor(b.format_id) }} />
              {b.interval && <span className="rng" style={{ left: `${b.interval[0]}%`, width: `${Math.max(0.4, b.interval[1] - b.interval[0])}%` }} />}
            </span>
            <span className="n">
              {b.expected.toFixed(2)}% <span className="faint">{b.protocol_id}</span>
            </span>
          </div>
        ))}
      </div>
      <figcaption className="faint" style={{ fontSize: 12.5, marginTop: 8 }}>
        Bar: expected accuracy with the protocol the advisor would use. Line: the range across the table values it rests on. The study measured each factor alone; this combination was not itself evaluated. Computed in the browser from the evidence files.
      </figcaption>
    </figure>
  );
}

export function RecommendationCard({ rec, source, bars }: { rec: Recommendation; source: string; bars: FormatBar[] }) {
  const s = rec.situation;
  return (
    <div className="fw-stack" style={{ gap: 20 }}>
      <div className="fw-card">
        <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
          <div className="label">
            <b>RECOMMENDED</b> / {rec.basis.replace(":", " ")}
            {rec.basis_note ? ` (${rec.basis_note})` : ""}
          </div>
          <Badge tone="accent">{source}</Badge>
        </div>
        <div className="fw-rec-head">
          <div>
            <div className="pair">
              {rec.format_id}
              <span className="plus">+</span>
              {rec.protocol_id}
            </div>
            <div className="muted" style={{ fontSize: 14 }}>
              {rec.format_name}, answered as {rec.protocol_name}
            </div>
          </div>
          <div className="fw-stat" style={{ textAlign: "right" }}>
            <div className="v">
              {rec.expected_accuracy.toFixed(2)}
              <small>%</small>
            </div>
            <div className="k">expected strict-call accuracy, {rec.rule.replace("_", " ")} rule</div>
          </div>
        </div>
        <Range value={rec.expected_accuracy} lo={rec.interval[0]} hi={rec.interval[1]} />
        <div className="faint" style={{ fontSize: 12.5, marginTop: 14 }}>
          Range {rec.interval[0].toFixed(2)} to {rec.interval[1].toFixed(2)} across the table values it rests on. This is not a confidence interval.
        </div>
        <div className="fw-kv">
          <div>
            <div className="k">Tool block</div>
            <div className="v">{rec.schema_tokens === null ? "n/a" : `~${rec.schema_tokens.toLocaleString("en-US")}`}</div>
            <div className="s">tokens, {rec.tokens_source === "rendered" ? "your tools, characters / 4" : "study, scaled to the count"}</div>
          </div>
          <div>
            <div className="k">Cost per request</div>
            <div className="v">{rec.cost_per_request === null ? "n/a" : rec.cost_per_request.toFixed(6)}</div>
            <div className="s">{s.price === "self_hosted" ? "self-hosted" : "frontier API"} price units</div>
          </div>
          <div>
            <div className="k">Catalogue</div>
            <div className="v">{rec.catalogue.strategy.replace("_", " ")}</div>
            <div className="s">{s.n_tools} tools, tier {s.tier}</div>
          </div>
          <div>
            <div className="k">Model</div>
            <div className="v" style={{ fontSize: 15 }}>
              {rec.resolution.family_label ?? rec.resolution.anchor ?? "unknown"}
            </div>
            <div className="s">matched by {rec.resolution.matched_by}</div>
          </div>
        </div>
        {rec.tied_with.length > 0 && (
          <p className="muted" style={{ fontSize: 14, marginTop: 16, marginBottom: 0 }}>
            Tied within 2.0: {rec.tied_with.map(label).join(", ")}.
          </p>
        )}
        <div className="row" style={{ marginTop: 18 }}>
          <CopyButton text={pythonFor(s)} label="Copy Python" className="fw-btn small" />
          <CopyButton text={cliFor(s)} label="Copy CLI" className="fw-btn small" />
          <Link to="/dashboard/playground" className="fw-btn small ghost">
            Render it in the playground
          </Link>
        </div>
      </div>

      <div className="fw-card">
        <h2 style={{ fontSize: 18 }}>Why</h2>
        <p style={{ marginBottom: 0 }}>{rec.explanation}</p>
      </div>

      {rec.warnings.length > 0 && (
        <div className="fw-callout warn" role="note">
          <strong>Warnings</strong>
          <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
            {rec.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="fw-card">
        <h2 style={{ fontSize: 18 }}>The eight core formats for this situation</h2>
        <FormatBars bars={bars} winner={rec.format_id} />
      </div>

      <div className="fw-grid2" style={{ alignItems: "start" }}>
        <div className="fw-card">
          <h2 style={{ fontSize: 18 }}>Evidence</h2>
          <EvidenceList rows={rec.evidence} />
        </div>
        <div className="fw-card" style={{ display: "grid", gap: 16 }}>
          <div>
            <h2 style={{ fontSize: 18 }}>Catalogue: {rec.catalogue.strategy.replace("_", " ")}</h2>
            <p className="muted" style={{ fontSize: 14 }}>{rec.catalogue.reason}</p>
            <EvidenceList rows={rec.catalogue.evidence} />
          </div>
          {rec.guard && (
            <div>
              <h2 style={{ fontSize: 18 }}>Guard: {rec.guard.action.replace("_", " ")}</h2>
              <p className="muted" style={{ fontSize: 14 }}>{rec.guard.reason}</p>
              <EvidenceList rows={rec.guard.evidence} />
            </div>
          )}
          {rec.surface && (
            <div>
              <h2 style={{ fontSize: 18 }}>Fitted surface</h2>
              <p className="muted" style={{ fontSize: 14, marginBottom: 0 }}>
                {fmtPct(rec.surface.predicted)} for {rec.surface.format_id} at this size, count and tier; {rec.surface.note}.
              </p>
            </div>
          )}
        </div>
      </div>

      <div className="fw-card">
        <h2 style={{ fontSize: 18 }}>Measure it instead</h2>
        <p className="muted" style={{ fontSize: 14 }}>{rec.measure_hint}</p>
        <code style={{ fontSize: 12.5 }}>toolform ab-test --base-url http://localhost:8000/v1 --model {s.model || "YOUR_MODEL"}</code>
      </div>

      <div className="tablewrap">
        <table>
          <caption className="sr-only">Every candidate format, ranked</caption>
          <thead>
            <tr>
              <th>format</th>
              <th>protocol</th>
              <th className="num">expected</th>
              <th className="num">tokens</th>
              <th className="num">cost / request</th>
              <th className="num">score</th>
            </tr>
          </thead>
          <tbody>
            <tr className="hl">
              <td>{rec.format_id}</td>
              <td>{rec.protocol_id}</td>
              <td className="num">{rec.expected_accuracy.toFixed(2)}%</td>
              <td className="num">{rec.schema_tokens?.toLocaleString("en-US") ?? "n/a"}</td>
              <td className="num">{rec.cost_per_request?.toFixed(6) ?? "n/a"}</td>
              <td className="num">winner</td>
            </tr>
            {rec.alternatives.map((a) => (
              <tr key={a.format_id}>
                <td>{a.format_id}</td>
                <td>{a.protocol_id}</td>
                <td className="num">{a.expected_accuracy.toFixed(2)}%</td>
                <td className="num">{a.schema_tokens?.toLocaleString("en-US") ?? "n/a"}</td>
                <td className="num">{a.cost_per_request?.toFixed(6) ?? "n/a"}</td>
                <td className="num">{a.score.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
