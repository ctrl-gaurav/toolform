import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Selection } from "../lib/evidence";
import { ChartFrame, pct, TooltipBox } from "./ChartFrame";

const STRATEGIES: [keyof Selection["mean"], string][] = [
  ["always_json", "always JSON Schema"],
  ["fitted_rule", "the fitted rule"],
  ["always_xml", "always XML"],
  ["lookup", "best per (count, tier)"],
  ["measure_eight", "measure eight"],
  ["oracle", "oracle (ceiling)"],
];

export function SelectionChart({ data }: { data: Selection }) {
  const rows = STRATEGIES.map(([k, label]) => ({ k, label, v: data.mean[k] as number }));
  return (
    <ChartFrame
      id="selection"
      title={`Measuring eight formats on the target model (${pct(data.mean.measure_eight)}) beats every rule`}
      file="selection.json"
      ariaLabel={`Mean accuracy by selection strategy, families held out: ${rows.map((r) => `${r.label} ${r.v}%`).join(", ")}.`}
      caption={
        <>
          Each strategy scored on measured accuracy with the family held out, over {data.cells.toLocaleString("en-US")} cells of the main grid, the count sweep and the
          tier sweep (tab_selection). The oracle picks the best format per condition in hindsight and is inflated by seed noise. The table view has every family.
        </>
      }
      table={
        <table>
          <thead>
            <tr>
              <th>held-out family</th>
              <th className="num">cond.</th>
              {STRATEGIES.map(([, l]) => (
                <th key={l} className="num">
                  {l}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.family}>
                <td>{r.family_label}</td>
                <td className="num">{r.conditions}</td>
                {STRATEGIES.map(([k]) => (
                  <td key={k} className="num">
                    {pct(r[k] as number)}
                  </td>
                ))}
              </tr>
            ))}
            <tr className="hl">
              <td>mean</td>
              <td className="num">{data.mean.conditions}</td>
              {STRATEGIES.map(([k]) => (
                <td key={k} className="num">
                  {pct(data.mean[k] as number)}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      }
    >
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={rows} layout="vertical" margin={{ top: 8, right: 64, bottom: 8, left: 8 }}>
          <CartesianGrid horizontal={false} />
          <XAxis type="number" domain={[0, 100]} tickFormatter={(v) => `${v}%`} tickLine={false} axisLine={false} />
          <YAxis type="category" dataKey="label" width={160} tickLine={false} axisLine={false} />
          <Tooltip cursor={{ fill: "var(--fw-accent-soft)" }} content={({ payload }) => (payload?.[0] ? <TooltipBox title={payload[0].payload.label} rows={[["mean accuracy", pct(payload[0].payload.v)]]} /> : null)} />
          <Bar dataKey="v" radius={[0, 4, 4, 0]} maxBarSize={26} isAnimationActive={false}>
            {rows.map((r) => (
              <Cell key={r.k} fill={r.k === "measure_eight" ? "var(--fw-accent)" : r.k === "oracle" ? "var(--fw-border-strong)" : "var(--fw-text-faint)"} />
            ))}
            <LabelList dataKey="v" position="right" formatter={(v: number) => `${v.toFixed(2)}%`} style={{ fill: "var(--fw-text)", fontFamily: "var(--fw-mono)", fontSize: 12 }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
