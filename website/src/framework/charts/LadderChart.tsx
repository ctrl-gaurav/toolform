import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Ladder } from "../lib/evidence";
import { ChartFrame, pct, TooltipBox } from "./ChartFrame";

export function LadderChart({ data }: { data: Ladder }) {
  const rows = data.rungs.map((r) => ({ ...r, short: r.format_id }));
  return (
    <ChartFrame
      id="ladder"
      title={`The parameter schema is worth ${data.gap.value?.toFixed(2)}% over tool names alone`}
      file="ladder.json"
      ariaLabel={`Schema ladder: ${rows.map((r) => `${r.format_id} ${r.accuracy}%`).join(", ")}.`}
      caption={
        <>
          Four rungs from tool names alone to the full JSON Schema, strict-call accuracy under the main rule, 8 tools, tier 3, 35 checkpoints (tab_ladder). The gap
          between the full schema and names alone is {data.gap.value?.toFixed(2)}% [{data.gap.interval?.[0].toFixed(2)}, {data.gap.interval?.[1].toFixed(2)}] at 8
          tools; it falls from +70.51 at one tool to +18.30 at 256 (tab_names_only).
        </>
      }
      table={
        <table>
          <thead>
            <tr>
              <th>rung</th>
              <th>what it shows</th>
              <th className="num">accuracy</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.format_id}>
                <td>{r.format_id}</td>
                <td className="wrapcell">{r.shows}</td>
                <td className="num">{pct(r.accuracy)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={rows} margin={{ top: 24, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="short" tickLine={false} axisLine={false} interval={0} />
          <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} tickLine={false} axisLine={false} width={48} />
          <Tooltip cursor={{ fill: "var(--fw-accent-soft)" }} content={({ payload }) => (payload?.[0] ? <TooltipBox title={String(payload[0].payload.format_id)} rows={[["shows", payload[0].payload.shows], ["accuracy", pct(payload[0].payload.accuracy)]]} /> : null)} />
          <Bar dataKey="accuracy" fill="var(--fw-s-xml)" radius={[4, 4, 0, 0]} maxBarSize={72}>
            <LabelList dataKey="accuracy" position="top" formatter={(v: number) => `${v.toFixed(2)}%`} style={{ fill: "var(--fw-text)", fontFamily: "var(--fw-mono)", fontSize: 12 }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
