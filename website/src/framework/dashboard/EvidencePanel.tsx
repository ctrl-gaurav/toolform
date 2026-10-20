import { docs } from "../lib/links";
import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useEvidence } from "../lib/evidence";
import { CostScatter } from "../charts/CostScatter";
import { CrossingHeatmap } from "../charts/CrossingHeatmap";
import { DisclosureChart } from "../charts/DisclosureChart";
import { FamilyHeatmap } from "../charts/FamilyHeatmap";
import { GraderChart } from "../charts/GraderChart";
import { InjectionChart } from "../charts/InjectionChart";
import { LadderChart } from "../charts/LadderChart";
import { SelectionChart } from "../charts/SelectionChart";
import { ToolCountChart } from "../charts/ToolCountChart";

export const CHARTS = [
  { id: "ladder", label: "Schema ladder" },
  { id: "graders", label: "Grading rules" },
  { id: "crossing", label: "Protocol by format" },
  { id: "tool-count", label: "Tool count" },
  { id: "injection", label: "Hidden instructions" },
  { id: "selection", label: "Selection strategies" },
  { id: "cost", label: "Tokens and accuracy" },
  { id: "families", label: "Families" },
  { id: "disclosure", label: "Two-stage disclosure" },
];

function Missing({ name }: { name: string }) {
  return <p className="muted">{name}.json did not load.</p>;
}

export function EvidencePanel() {
  const [params, setParams] = useSearchParams();
  const chart = params.get("chart");
  const ladder = useEvidence("ladder");
  const core = useEvidence("core_main");
  const crossing = useEvidence("protocol_crossing");
  const count = useEvidence("tool_count");
  const injection = useEvidence("injection");
  const selection = useEvidence("selection");
  const cost = useEvidence("cost");
  const formats = useEvidence("formats");
  const families = useEvidence("families");
  const disclosure = useEvidence("disclosure");
  const loaded = [ladder, core, crossing, count, injection, selection, cost, families, disclosure].every((x) => !x.loading);

  useEffect(() => {
    if (!chart || !loaded) return;
    const t = window.setTimeout(() => document.getElementById(`chart-${chart}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
    return () => window.clearTimeout(t);
  }, [chart, loaded]);

  return (
    <div style={{ paddingTop: 8 }}>
      <nav className="fw-chartnav" aria-label="Charts">
        {CHARTS.map((c) => (
          <Link
            key={c.id}
            to={`/dashboard/evidence?chart=${c.id}`}
            className={chart === c.id ? "active" : undefined}
            aria-current={chart === c.id ? "location" : undefined}
            onClick={() => setParams({ chart: c.id }, { replace: true })}
          >
            {c.label}
          </Link>
        ))}
      </nav>
      <p className="muted" style={{ fontSize: 14 }}>
        Every chart states its finding in the title and names its table in the caption. The numbers are the paper's tables as the evidence files ship them;{" "}
        <a href={docs("evidence")}>the evidence page</a> says how they are built.
      </p>
      <div className="fw-stack" style={{ gap: 24, marginTop: 16 }}>
        {ladder.data ? <LadderChart data={ladder.data} /> : !ladder.loading && <Missing name="ladder" />}
        {core.data ? <GraderChart rows={core.data.rows} /> : !core.loading && <Missing name="core_main" />}
        {crossing.data ? <CrossingHeatmap data={crossing.data} /> : !crossing.loading && <Missing name="protocol_crossing" />}
        {count.data ? <ToolCountChart data={count.data} /> : !count.loading && <Missing name="tool_count" />}
        {injection.data ? <InjectionChart data={injection.data} /> : !injection.loading && <Missing name="injection" />}
        {selection.data ? <SelectionChart data={selection.data} /> : !selection.loading && <Missing name="selection" />}
        {cost.data ? <CostScatter data={cost.data} formats={formats.data} /> : !cost.loading && <Missing name="cost" />}
        {families.data ? <FamilyHeatmap rows={families.data.rows} /> : !families.loading && <Missing name="families" />}
        {disclosure.data ? <DisclosureChart data={disclosure.data} /> : !disclosure.loading && <Missing name="disclosure" />}
      </div>
    </div>
  );
}
