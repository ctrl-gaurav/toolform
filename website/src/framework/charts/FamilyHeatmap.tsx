import type { FamilyRow } from "../lib/evidence";
import { CORE_FORMATS } from "../lib/render";
import { ChartFrame } from "./ChartFrame";
import { HeatTable } from "./CrossingHeatmap";

const SHORT: Record<string, string> = {
  xml_schema: "XML",
  natural_language: "NL",
  python_stub: "Py",
  json_schema_openai: "JSON",
  yaml_schema: "YAML",
  typescript: "TS",
  markdown_table: "MD",
  json_minimal: "min.",
};

export function FamilyHeatmap({ rows }: { rows: FamilyRow[] }) {
  const byLabel = Object.fromEntries(rows.map((r) => [r.label, r]));
  const blocks: Record<string, string> = {};
  let prev = "";
  for (const r of rows) {
    if (r.kind !== prev) blocks[r.label] = r.kind === "open" ? "Open-weight families, one row per family" : r.kind === "anchor_open" ? "Anchors, open-weight, through a shared endpoint" : "Anchors, proprietary";
    prev = r.kind;
  }
  const cols = CORE_FORMATS.map((f) => SHORT[f]);
  const colF = Object.fromEntries(CORE_FORMATS.map((f) => [SHORT[f], f]));
  const table = (
    <HeatTable
      rows={rows.map((r) => r.label)}
      cols={[...cols, "spread"]}
      value={(l, c) => (c === "spread" ? byLabel[l].spread : byLabel[l].accuracy[colF[c]] ?? null)}
      lo={0}
      hi={100}
      rowLabel={(l) => `${l}${byLabel[l].kind === "open" ? ` (${byLabel[l].checkpoints})` : ""}`}
      caption="Strict-call accuracy per family and format"
      blocks={blocks}
    />
  );
  return (
    <ChartFrame
      id="families"
      title="The best format depends on the model family"
      file="families.json"
      ariaLabel={`Heatmap of strict-call accuracy for ${rows.length} families and anchor models across the eight core formats.`}
      caption="Strict-call accuracy under the main rule, 8 tools, tier 3, single call (tab_models_main). An open-weight row averages the family's checkpoints (count in brackets); an anchor row is one model and enters no fit. Spread is the best format minus the worst."
      table={table}
    >
      <div style={{ overflowX: "auto" }}>{table}</div>
    </ChartFrame>
  );
}
