import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { CoreMainRow } from "../lib/evidence";
import { CORE_FORMAT_LABELS, isCoreFormat } from "../lib/render";
import { ChartFrame, Legend, pct, TooltipBox } from "./ChartFrame";

const SERIES = [
  { key: "main", label: "main", color: "var(--fw-s-xml)" },
  { key: "symmetric", label: "symmetric", color: "var(--fw-s-nl)" },
  { key: "as_written", label: "as written", color: "var(--fw-s-py)" },
] as const;

export function GraderChart({ rows }: { rows: CoreMainRow[] }) {
  const data = rows.map((r) => ({ ...r, label: isCoreFormat(r.format_id) ? CORE_FORMAT_LABELS[r.format_id] : r.format_id }));
  const xml = rows.find((r) => r.format_id === "xml_schema");
  return (
    <ChartFrame
      id="graders"
      title="The same answers rank the formats differently under each grading rule"
      file="core_main.json"
      ariaLabel={`Accuracy by format under three grading rules. ${data.map((d) => `${d.label}: main ${d.main}, symmetric ${d.symmetric}, as written ${d.as_written}`).join("; ")}.`}
      caption={
        <>
          61,200 answers on the main grid (8 tools, tier 3, 51 checkpoints, seeds 0 to 2), each format with its default protocol, graded three ways (tab_main). XML minus
          JSON Schema: {xml?.minus_json_main.value?.toFixed(2)} under the main rule, {xml?.minus_json_as_written.value?.toFixed(2)} as written.
        </>
      }
      table={
        <table>
          <thead>
            <tr>
              <th>format</th>
              <th>protocol</th>
              <th className="num">main</th>
              <th className="num">symmetric</th>
              <th className="num">as written</th>
              <th className="num">real tools</th>
            </tr>
          </thead>
          <tbody>
            {data.map((r) => (
              <tr key={r.format_id}>
                <td>{r.label}</td>
                <td>{r.protocol_id}</td>
                <td className="num">{pct(r.main)} ({r.rank_main})</td>
                <td className="num">{pct(r.symmetric)} ({r.rank_symmetric})</td>
                <td className="num">{pct(r.as_written)} ({r.rank_as_written})</td>
                <td className="num">{pct(r.real_accuracy)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      <Legend items={SERIES.map((s) => ({ label: s.label, color: s.color }))} />
      <ResponsiveContainer width="100%" height={320}>
        <BarChart data={data} margin={{ top: 12, right: 8, bottom: 8, left: 0 }} barGap={2} barCategoryGap="22%">
          <CartesianGrid vertical={false} />
          <XAxis dataKey="label" tickLine={false} axisLine={false} interval={0} angle={-20} textAnchor="end" height={56} />
          <YAxis domain={[0, 80]} tickFormatter={(v) => `${v}%`} tickLine={false} axisLine={false} width={48} />
          <Tooltip
            cursor={{ fill: "var(--fw-accent-soft)" }}
            content={({ payload }) => {
              const p = payload?.[0]?.payload;
              return p ? <TooltipBox title={`${p.label} (${p.protocol_id})`} rows={SERIES.map((s) => [s.label, `${pct(p[s.key])}, rank ${p[`rank_${s.key}`]}`] as [string, string])} /> : null;
            }}
          />
          {SERIES.map((s) => (
            <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color} radius={[4, 4, 0, 0]} maxBarSize={22} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
