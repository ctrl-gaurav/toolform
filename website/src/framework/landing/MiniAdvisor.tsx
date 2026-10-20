import { useMemo, useState } from "react";
import { fmtPct, recommend } from "../lib/advisor";
import { useAdvisorEvidence } from "../lib/evidence";
import { CORE_FORMAT_LABELS, isCoreFormat } from "../lib/render";
import { ButtonLink } from "../ui/Button";
import { Field } from "../ui/Field";

const COUNTS = [1, 4, 8, 16, 32, 64, 128, 256];

/* A two-input version of the advisor, computed in the browser. */
export function MiniAdvisor() {
  const { evidence, loading } = useAdvisorEvidence();
  const [family, setFamily] = useState("qwen3");
  const [n, setN] = useState(8);
  const families = evidence?.families.rows.filter((r) => r.kind === "open") ?? [];
  const rec = useMemo(() => (evidence ? recommend(evidence, { family, n_tools: n }) : null), [evidence, family, n]);
  const label = (f: string) => (isCoreFormat(f) ? CORE_FORMAT_LABELS[f] : f);
  return (
    <div className="fw-card fw-mini">
      <div>
        <div className="label" style={{ marginBottom: 16 }}>
          <b>TRY</b> / THE ADVISOR
        </div>
        <Field label="Model family">
          <select value={family} onChange={(e) => setFamily(e.target.value)} disabled={!evidence}>
            {families.map((r) => (
              <option key={r.family!} value={r.family!}>
                {r.label} ({r.checkpoints} checkpoint{r.checkpoints === 1 ? "" : "s"})
              </option>
            ))}
          </select>
        </Field>
        <Field label="Tools shown to the model">
          <select value={n} onChange={(e) => setN(Number(e.target.value))} disabled={!evidence}>
            {COUNTS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </Field>
        <p className="faint" style={{ fontSize: 13 }}>
          Tier 3, the main grading rule. The full advisor takes a model id, a token budget, a cost objective and your own tools.
        </p>
      </div>
      <div className="out" aria-live="polite">
        {loading && <p className="muted">Loading the evidence.</p>}
        {!loading && !rec && <p className="muted">The evidence files did not load, so the advisor cannot run here.</p>}
        {rec && (
          <>
            <div className="label">Recommended</div>
            <div className="pair">
              {rec.format_id} <span>+</span> {rec.protocol_id}
            </div>
            <div className="row" style={{ gap: 24 }}>
              <div className="fw-stat">
                <div className="v" style={{ fontSize: 34 }}>{fmtPct(rec.expected_accuracy)}</div>
                <div className="k">
                  expected, range {rec.interval[0].toFixed(2)} to {rec.interval[1].toFixed(2)} across the table values it rests on
                </div>
              </div>
              <div className="fw-stat">
                <div className="v" style={{ fontSize: 34 }}>{rec.catalogue.strategy.replace("_", " ")}</div>
                <div className="k">catalogue strategy</div>
              </div>
            </div>
            <p className="muted" style={{ fontSize: 14, margin: 0 }}>
              {label(rec.format_id)} for the {rec.resolution.family_label} family.{" "}
              {rec.alternatives[0] && `Next: ${label(rec.alternatives[0].format_id)} at ${fmtPct(rec.alternatives[0].expected_accuracy)}.`}
            </p>
            <div>
              <ButtonLink to={`/dashboard/advisor?family=${family}&n=${n}`} small>
                Open the full advisor
              </ButtonLink>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
