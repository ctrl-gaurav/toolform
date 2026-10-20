import { Bar, CartesianGrid, Cell, ComposedChart, LabelList, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import type { Injection } from "../lib/evidence";
import { CORE_FORMAT_LABELS, isCoreFormat } from "../lib/render";
import { ChartFrame, Legend, pct, TooltipBox } from "./ChartFrame";
import { fmtColor } from "./palette";

export function InjectionChart({ data }: { data: Injection }) {
  const label = (f: string) => (isCoreFormat(f) ? CORE_FORMAT_LABELS[f] : f);
  const rows = data.formats.map((r) => ({ ...r, label: label(r.format_id) }));
  const shown = rows.filter((r) => r.format_id !== "json_minimal").map((r) => r.hijack);
  const trust = data.trust;
  return (
    <ChartFrame
      id="injection"
      title={`An instruction hidden in a tool description is followed on ${Math.min(...shown).toFixed(2)} to ${Math.max(...shown).toFixed(2)}% of turns in every format that shows one`}
      file="injection.json"
      ariaLabel={`Hijack followed by format: ${rows.map((r) => `${r.label} ${r.hijack}%`).join(", ")}.`}
      caption={
        <>
          One plain sentence in one tool's description, 51 checkpoints, 8 tools, tier 3, seeds 0 to 2 (tab_pressure). Bars: the share of turns writing the value the
          sentence asked for. Dots: the share calling a decoy tool that asked to be called first. The matched control with no sentence is 0.00 everywhere. The minimal
          schema shows no description. The trust-line experiment (tab_injection_trust) is in the table view.
        </>
      }
      table={
        <table>
          <thead>
            <tr>
              <th>payload, trust line</th>
              <th>format</th>
              <th className="num">followed</th>
              <th className="num">95% interval</th>
              <th className="num">credited and valid</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`p-${r.format_id}`}>
                <td>injection treatment</td>
                <td>{r.label}</td>
                <td className="num">{pct(r.hijack)}</td>
                <td className="num">decoy {pct(r.decoy)}</td>
                <td className="num">acc. {pct(r.acc_control)} to {pct(r.acc_hijack)}</td>
              </tr>
            ))}
            {trust.map((t, i) => (
              <tr key={`t-${i}`}>
                <td>
                  {t.payload}, trust line {t.trust_line ? "on" : "off"}
                </td>
                <td>{label(t.format_id)}</td>
                <td className="num">{pct(t.followed)}</td>
                <td className="num">{t.interval ? `[${t.interval[0].toFixed(2)}, ${t.interval[1].toFixed(2)}]` : "n/a"}</td>
                <td className="num">{pct(t.credited_valid)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      <Legend items={[{ label: "hijack followed (bar)", color: "var(--fw-text-muted)" }, { label: "decoy followed (dot)", color: "var(--fw-text)", shape: "dot" }]} />
      <ResponsiveContainer width="100%" height={320}>
        <ComposedChart data={rows} margin={{ top: 12, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="label" tickLine={false} axisLine={false} interval={0} angle={-20} textAnchor="end" height={56} />
          <YAxis domain={[0, 60]} tickFormatter={(v) => `${v}%`} tickLine={false} axisLine={false} width={48} />
          <Tooltip
            cursor={{ fill: "var(--fw-accent-soft)" }}
            content={({ payload }) => {
              const p = payload?.[0]?.payload;
              return p ? (
                <TooltipBox
                  title={p.label}
                  rows={[
                    ["hijack followed", pct(p.hijack)],
                    ["decoy followed", pct(p.decoy)],
                    ["accuracy, control", pct(p.acc_control)],
                    ["accuracy, hijack", pct(p.acc_hijack)],
                  ]}
                />
              ) : null;
            }}
          />
          <Bar dataKey="hijack" radius={[4, 4, 0, 0]} maxBarSize={48} isAnimationActive={false}>
            {rows.map((r) => (
              <Cell key={r.format_id} fill={fmtColor(r.format_id)} />
            ))}
            <LabelList dataKey="hijack" position="top" formatter={(v: number) => `${v.toFixed(2)}%`} style={{ fill: "var(--fw-text)", fontFamily: "var(--fw-mono)", fontSize: 11 }} />
          </Bar>
          <Scatter dataKey="decoy" fill="var(--fw-text)" shape="circle" isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
