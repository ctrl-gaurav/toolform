import { useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ToolCount } from "../lib/evidence";
import { CORE_FORMAT_LABELS, CORE_FORMATS, isCoreFormat } from "../lib/render";
import { ChartFrame, Legend, pct, TooltipBox } from "./ChartFrame";
import { fmtColor } from "./palette";

export function ToolCountChart({ data }: { data: ToolCount }) {
  const [focus, setFocus] = useState<string>("all");
  const rows = data.counts.map((n, i) => {
    const r: Record<string, number | string> = { n: String(n) };
    for (const f of CORE_FORMATS) if (data.accuracy[f]) r[f] = data.accuracy[f][i];
    const o = data.overall.find((x) => x.n_tools === n);
    r.empty = o?.empty ?? 0;
    return r;
  });
  const first = data.overall[0];
  const last = data.overall[data.overall.length - 1];
  const label = (f: string) => (isCoreFormat(f) ? CORE_FORMAT_LABELS[f] : f);
  return (
    <ChartFrame
      id="tool-count"
      title={`Going from 1 to 256 tools costs ${(first.strict - last.strict).toFixed(2)}% of strict-call accuracy`}
      file="tool_count.json"
      ariaLabel={`Accuracy by tool count for eight formats. Overall ${first.strict}% at 1 tool and ${last.strict}% at 256, where ${last.empty}% of turns are empty.`}
      controls={
        <select aria-label="Highlight a format" value={focus} onChange={(e) => setFocus(e.target.value)} style={{ width: 170, height: 32 }}>
          <option value="all">all formats</option>
          {CORE_FORMATS.map((f) => (
            <option key={f} value={f}>
              {label(f)}
            </option>
          ))}
        </select>
      }
      caption={
        <>
          The count sweep: tier 3, single calls, the eight core formats, 51 checkpoints, main rule (tab_count_by_format, tab_count). The shaded area is the share of turns
          that returned nothing at all, pooled over formats: past 64 tools a column partly measures the context window. At 256 tools, conditioning on cells under 5%
          empty gives {pct(data.empty_filtered_256)}. Retrieval on a 128-tool panel: {data.retrieval.map((r) => `${r.label} ${pct(r.accuracy)}`).join("; ")}.
        </>
      }
      table={
        <table>
          <thead>
            <tr>
              <th>tools</th>
              {CORE_FORMATS.map((f) => (
                <th key={f} className="num">
                  {label(f)}
                </th>
              ))}
              <th className="num">empty turns</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.n}>
                <td>{r.n}</td>
                {CORE_FORMATS.map((f) => (
                  <td key={f} className="num">
                    {pct(r[f] as number, 1)}
                  </td>
                ))}
                <td className="num">{pct(r.empty as number)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      <Legend items={[...CORE_FORMATS.map((f) => ({ label: label(f), color: fmtColor(f), shape: "line" as const })), { label: "empty turns (pooled)", color: "var(--fw-border-strong)" }]} />
      <ResponsiveContainer width="100%" height={340}>
        <ComposedChart data={rows} margin={{ top: 12, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="n" tickLine={false} axisLine={false} label={{ value: "tools shown (log scale)", position: "insideBottom", offset: -4 }} height={40} />
          <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} tickLine={false} axisLine={false} width={48} />
          <Tooltip
            content={({ payload, label: l }) =>
              payload?.length ? (
                <TooltipBox
                  title={`${l} tools`}
                  rows={[
                    ...CORE_FORMATS.map((f) => [label(f), pct(payload[0].payload[f], 1)] as [string, string]),
                    ["empty turns", pct(payload[0].payload.empty)],
                  ]}
                />
              ) : null
            }
          />
          <Area dataKey="empty" fill="var(--fw-border-strong)" fillOpacity={0.35} stroke="none" isAnimationActive={false} />
          {CORE_FORMATS.map((f) => (
            <Line
              key={f}
              dataKey={f}
              stroke={fmtColor(f)}
              strokeWidth={focus === f ? 3 : 2}
              strokeOpacity={focus === "all" || focus === f ? 1 : 0.2}
              dot={{ r: focus === f ? 4 : 2.5, strokeWidth: 0, fill: fmtColor(f) }}
              activeDot={{ r: 5 }}
              isAnimationActive={false}
            />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
