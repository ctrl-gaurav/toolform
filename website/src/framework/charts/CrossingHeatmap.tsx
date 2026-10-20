import { Fragment, useState } from "react";
import type { Crossing, Rule } from "../lib/evidence";
import { CORE_FORMAT_LABELS, isCoreFormat } from "../lib/render";
import { Segmented } from "../ui/Segmented";
import { ChartFrame, pct } from "./ChartFrame";
import { inkOn, seqColor, useThemeColors } from "./palette";

export function HeatTable({ rows, cols, value, lo, hi, rowLabel, caption, blocks }: { rows: string[]; cols: string[]; value: (r: string, c: string) => number | null; lo: number; hi: number; rowLabel: (r: string) => string; caption: string; blocks?: Record<string, string> }) {
  const c = useThemeColors();
  return (
    <table className="fw-heat">
      <caption className="sr-only">{caption}</caption>
      <thead>
        <tr>
          <th className="rowh" />
          {cols.map((x) => (
            <th key={x} scope="col">
              {x}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <Fragment key={r}>
            {blocks?.[r] && (
              <tr>
                <th colSpan={cols.length + 1} className="rowh" style={{ paddingTop: 14 }}>
                  {blocks[r]}
                </th>
              </tr>
            )}
            <tr>
              <th scope="row" className="rowh" style={{ fontFamily: "var(--fw-sans)", fontSize: 13, color: "var(--fw-text)" }}>
                {rowLabel(r)}
              </th>
              {cols.map((x) => {
                const v = value(r, x);
                const bg = v === null ? "transparent" : seqColor((v - lo) / Math.max(1, hi - lo), c["--fw-seq-lo"], c["--fw-seq-hi"]);
                return (
                  <td key={x} className="cell" style={{ background: bg, color: v === null ? "var(--fw-text-faint)" : inkOn(bg, "#FFFFFF", "#0A1018") }}>
                    {v === null ? "n/a" : v.toFixed(1)}
                  </td>
                );
              })}
            </tr>
          </Fragment>
        ))}
      </tbody>
    </table>
  );
}

export function CrossingHeatmap({ data }: { data: Crossing }) {
  const [rule, setRule] = useState<Rule>("main");
  const r = data.rules[rule];
  const formats = Object.keys(r.cells).sort((a, b) => (r.row_mean[b] ?? 0) - (r.row_mean[a] ?? 0));
  const all = formats.flatMap((f) => data.protocols.map((p) => r.cells[f][p]));
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const label = (f: string) => (isCoreFormat(f) ? CORE_FORMAT_LABELS[f] : f);
  const table = (
    <HeatTable
      rows={formats}
      cols={[...data.protocols, "mean"]}
      value={(f, p) => (p === "mean" ? r.row_mean[f] : r.cells[f][p])}
      lo={lo}
      hi={hi}
      rowLabel={label}
      caption={`Format by protocol, ${rule} rule`}
    />
  );
  return (
    <ChartFrame
      id="crossing"
      title={`The answer protocol moves accuracy ${data.ratios[rule].toFixed(2)} times as much as the format under the ${rule.replace("_", " ")} rule`}
      file="protocol_crossing.json"
      ariaLabel={`Heatmap of strict-call accuracy for eight formats by five protocols under the ${rule} rule. Protocol spread over format spread: ${data.ratios[rule]}.`}
      controls={
        <Segmented
          label="Grading rule"
          value={rule}
          onChange={setRule}
          options={[
            { value: "main", label: "main" },
            { value: "symmetric", label: "symmetric" },
            { value: "as_written", label: "as written" },
          ]}
        />
      }
      caption={
        <>
          Every core format paired with five answer protocols: {data.cells.toLocaleString("en-US")} cells, {data.checkpoints} checkpoints, seeds 0 to 2, tier 3
          (tab_protocol). Darker is more accurate. Ratios of protocol spread to format spread: {data.ratios.main.toFixed(2)} main, {data.ratios.symmetric.toFixed(2)}{" "}
          symmetric, {data.ratios.as_written.toFixed(2)} as written. Column means: {data.protocols.map((p) => `${p} ${pct(r.col_mean[p])}`).join(", ")}.
        </>
      }
      table={table}
    >
      <div style={{ overflowX: "auto" }}>{table}</div>
    </ChartFrame>
  );
}
