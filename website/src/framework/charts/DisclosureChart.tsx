import { Bar, BarChart, CartesianGrid, ErrorBar, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Disclosure } from "../lib/evidence";
import { ChartFrame, Legend, pct, TooltipBox } from "./ChartFrame";

const ARMS = [
  { key: "names", label: "names, then the schema", color: "var(--fw-s-xml)" },
  { key: "names_desc", label: "names and descriptions, then the schema", color: "var(--fw-s-nl)" },
  { key: "oracle", label: "oracle selection (ceiling)", color: "var(--fw-s-py)" },
] as const;

export function DisclosureChart({ data }: { data: Disclosure }) {
  const counts = Array.from(new Set(data.second_design.map((r) => r.n_tools))).sort((a, b) => a - b);
  const rows = counts.map((n) => {
    const r: Record<string, unknown> = { n: String(n) };
    for (const a of ARMS) {
      const x = data.second_design.find((d) => d.n_tools === n && d.arm === a.key);
      r[a.key] = x?.minus_json.value ?? null;
      r[`${a.key}_err`] = x?.minus_json.interval ? [(x.minus_json.value ?? 0) - x.minus_json.interval[0], x.minus_json.interval[1] - (x.minus_json.value ?? 0)] : [0, 0];
      r[`${a.key}_row`] = x;
    }
    return r;
  });
  return (
    <ChartFrame
      id="disclosure"
      title="Names first and one schema second loses on short lists and gains on long ones"
      file="disclosure.json"
      ariaLabel={`Two-stage disclosure minus one-shot JSON Schema by tool count. ${rows.map((r) => `${r.n} tools: names ${r.names}, names and descriptions ${r.names_desc}`).join("; ")}.`}
      caption={
        <>
          The second two-stage design against the one-shot JSON Schema block, paired on checkpoint, count and seed, 53 checkpoints, three seeds of 40 requests (tab_disclosure_v2).
          Error bars are 95% checkpoint bootstrap intervals. A reply that names no tool is a selection failure. At 256 tools the one-shot prompt fills the window and the
          two-stage prompts do not.
        </>
      }
      table={
        <table>
          <thead>
            <tr>
              <th>tools</th>
              <th>arm</th>
              <th className="num">selected</th>
              <th className="num">failed</th>
              <th className="num">call</th>
              <th className="num">one-shot JSON</th>
              <th className="num">minus JSON</th>
              <th className="num">sel. tokens</th>
            </tr>
          </thead>
          <tbody>
            {data.second_design.map((r, i) => (
              <tr key={i}>
                <td>{r.n_tools}</td>
                <td>{ARMS.find((a) => a.key === r.arm)?.label}</td>
                <td className="num">{pct(r.selected)}</td>
                <td className="num">{pct(r.failed)}</td>
                <td className="num">{pct(r.call)}</td>
                <td className="num">{pct(r.json)}</td>
                <td className="num">
                  {r.minus_json.value !== null ? `${r.minus_json.value >= 0 ? "+" : ""}${r.minus_json.value.toFixed(2)}` : "n/a"}
                  {r.minus_json.interval ? ` [${r.minus_json.interval[0].toFixed(2)}, ${r.minus_json.interval[1].toFixed(2)}]` : ""}
                </td>
                <td className="num">{r.selection_tokens.toLocaleString("en-US")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      <Legend items={ARMS.map((a) => ({ label: a.label, color: a.color }))} />
      <ResponsiveContainer width="100%" height={320}>
        <BarChart data={rows} margin={{ top: 12, right: 16, bottom: 8, left: 0 }} barGap={2}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="n" tickLine={false} axisLine={false} label={{ value: "tools in the catalogue", position: "insideBottom", offset: -4 }} height={40} />
          <YAxis tickFormatter={(v) => `${v > 0 ? "+" : ""}${v}`} tickLine={false} axisLine={false} width={48} />
          <ReferenceLine y={0} stroke="var(--fw-text-faint)" />
          <Tooltip
            cursor={{ fill: "var(--fw-accent-soft)" }}
            content={({ payload, label }) =>
              payload?.length ? (
                <TooltipBox
                  title={`${label} tools, minus one-shot JSON`}
                  rows={ARMS.map((a) => {
                    const v = payload[0].payload[a.key] as number | null;
                    return [a.label, v === null ? "n/a" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}`] as [string, string];
                  })}
                />
              ) : null
            }
          />
          {ARMS.map((a) => (
            <Bar key={a.key} dataKey={a.key} fill={a.color} maxBarSize={26} isAnimationActive={false}>
              <ErrorBar dataKey={`${a.key}_err`} width={4} stroke="var(--fw-text)" strokeWidth={1} />
            </Bar>
          ))}
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
