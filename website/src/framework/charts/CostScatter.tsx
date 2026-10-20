import { CartesianGrid, Line, ComposedChart, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import type { Cost, FormatEntry } from "../lib/evidence";
import { CORE_FORMAT_LABELS, CORE_FORMATS, isCoreFormat } from "../lib/render";
import { ChartFrame, Legend, pct, TooltipBox } from "./ChartFrame";
import { fmtColor } from "./palette";

export function CostScatter({ data, formats }: { data: Cost; formats: Record<string, FormatEntry> | null }) {
  const nested = data.frontier && !Array.isArray(data.frontier) ? data.frontier : null;
  const rawPoints = data.points ?? nested?.points ?? [];
  const rawFrontier = Array.isArray(data.frontier) ? data.frontier : nested?.frontier ?? [];
  const points = rawPoints.filter((p) => p.call_exact !== null).map((p) => ({ ...p, core: isCoreFormat(p.format_id), novel: formats?.[p.format_id]?.novel ?? false }));
  const frontier = [...rawFrontier].sort((a, b) => a.tokens - b.tokens);
  const label = (f: string) => (isCoreFormat(f) ? CORE_FORMAT_LABELS[f] : f);
  return (
    <ChartFrame
      id="cost"
      title="The cheapest format and the most accurate one are at opposite ends"
      file="cost.json"
      ariaLabel={`Accuracy against schema tokens for ${points.length} formats, with the cost frontier. On the main grid the minimal schema uses ${data.rows.find((r) => r.format_id === "json_minimal")?.schema} tokens and XML ${data.rows.find((r) => r.format_id === "xml_schema")?.schema}.`}
      caption={
        <>
          Every study format from the site export (mean schema tokens against strict-call accuracy over all its cells), the eight core formats coloured, the frontier as a
          line; x is on a log scale. The paper's table for the core eight at 8 tools and tier 3 (tab_cost), with two price vectors, is in the table view. Invented formats are
          marked (novel) in the tooltip.
        </>
      }
      table={
        <table>
          <thead>
            <tr>
              <th>format</th>
              <th className="num">acc.</th>
              <th className="num">schema</th>
              <th className="num">prompt</th>
              <th className="num">completion</th>
              <th className="num">acc / 1k tok</th>
              <th className="num">acc / $ (A)</th>
              <th className="num">acc / $ (B)</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.format_id}>
                <td>{label(r.format_id)}</td>
                <td className="num">{pct(r.accuracy)}</td>
                <td className="num">{r.schema.toLocaleString("en-US")}</td>
                <td className="num">{r.prompt.toLocaleString("en-US")}</td>
                <td className="num">{r.completion}</td>
                <td className="num">{r.acc_per_1k.toFixed(3)}</td>
                <td className="num">{r.acc_per_price_a.toLocaleString("en-US")}</td>
                <td className="num">{r.acc_per_price_b.toLocaleString("en-US")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      <Legend
        items={[
          ...CORE_FORMATS.map((f) => ({ label: CORE_FORMAT_LABELS[f], color: fmtColor(f), shape: "dot" as const })),
          { label: "another study format", color: "var(--fw-text-faint)", shape: "dot" },
          { label: "cost frontier", color: "var(--fw-accent)", shape: "line" },
        ]}
      />
      <ResponsiveContainer width="100%" height={360}>
        <ComposedChart margin={{ top: 12, right: 16, bottom: 16, left: 0 }}>
          <CartesianGrid />
          <XAxis type="number" dataKey="tokens" scale="log" domain={[400, 20000]} ticks={[500, 1000, 2000, 5000, 10000, 20000]} tickFormatter={(v) => Number(v).toLocaleString("en-US")} tickLine={false} axisLine={false} label={{ value: "mean schema tokens (log scale)", position: "insideBottom", offset: -10 }} allowDuplicatedCategory={false} />
          <YAxis type="number" dataKey="call_exact" domain={[0, 80]} tickFormatter={(v) => `${v}%`} tickLine={false} axisLine={false} width={48} />
          <Tooltip
            content={({ payload }) => {
              const p = payload?.[0]?.payload;
              return p ? <TooltipBox title={`${p.format_id}${p.novel ? " (novel)" : ""}`} rows={[["accuracy", pct(p.call_exact)], ["schema tokens", Number(p.tokens).toLocaleString("en-US")]]} /> : null;
            }}
          />
          <Line data={frontier} dataKey="call_exact" stroke="var(--fw-accent)" strokeWidth={2} dot={false} isAnimationActive={false} type="stepAfter" />
          <Scatter data={points.filter((p) => !p.core)} isAnimationActive={false} fill="var(--fw-text-faint)" shape={(props: { cx?: number; cy?: number }) => <circle cx={props.cx} cy={props.cy} r={3.5} fill="var(--fw-text-faint)" />} />
          <Scatter
            data={points.filter((p) => p.core)}
            isAnimationActive={false}
            shape={(props: { cx?: number; cy?: number; payload?: { format_id: string } }) => (
              <circle cx={props.cx} cy={props.cy} r={7} fill={fmtColor(props.payload?.format_id ?? "")} stroke="var(--fw-surface)" strokeWidth={2} />
            )}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
