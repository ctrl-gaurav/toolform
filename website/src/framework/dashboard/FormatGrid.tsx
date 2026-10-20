import { CORE_FORMAT_LABELS, CORE_FORMATS, DEFAULT_PROTOCOL, renderFormat, type RenderOptions } from "../lib/render";
import type { CoreMainRow } from "../lib/evidence";
import { estimateTokens } from "../lib/tokens";
import type { ToolIR } from "../lib/tools";
import { fmtColor } from "../charts/palette";
import { CodeBlock } from "../ui/CodeBlock";

/* The eight core formats for the same tools, with tokens and the main grid
 * accuracy of each format from tab_main. */
export function FormatGrid({ tools, options, coreMain }: { tools: ToolIR[]; options: Partial<RenderOptions>; coreMain: CoreMainRow[] }) {
  const rows = CORE_FORMATS.map((f) => {
    let text = "";
    let error: string | null = null;
    try {
      text = renderFormat(tools, f, options);
    } catch (e) {
      error = (e as Error).message;
    }
    return { f, text, error, tokens: text ? estimateTokens(text) : 0, acc: coreMain.find((r) => r.format_id === f)?.main ?? null };
  }).sort((a, b) => a.tokens - b.tokens);
  const min = Math.min(...rows.map((r) => r.tokens).filter(Boolean));
  return (
    <div className="fw-fmtgrid">
      {rows.map((r) => (
        <article key={r.f} className="fw-card fw-fmtcard" style={{ padding: 16 }}>
          <header>
            <h3>
              <span className="fw-swatch" style={{ background: fmtColor(r.f) }} aria-hidden="true" />
              {CORE_FORMAT_LABELS[r.f]} <span className="faint mono" style={{ fontSize: 12, fontWeight: 400 }}>{r.f}</span>
            </h3>
            <span className="mono" style={{ fontSize: 12.5 }}>
              ~{r.tokens.toLocaleString("en-US")} tok{min && r.tokens !== min ? ` (${(r.tokens / min).toFixed(1)}x)` : ""}
            </span>
          </header>
          <p className="faint" style={{ fontSize: 12.5, margin: "0 0 10px" }}>
            {DEFAULT_PROTOCOL[r.f]} · main grid {r.acc === null ? "n/a" : `${r.acc.toFixed(2)}%`} (tab_main)
          </p>
          {r.error ? <p style={{ color: "var(--fw-danger)" }}>Render failed: {r.error}</p> : <CodeBlock code={r.text} title={`${r.text.length.toLocaleString("en-US")} characters`} />}
        </article>
      ))}
    </div>
  );
}
