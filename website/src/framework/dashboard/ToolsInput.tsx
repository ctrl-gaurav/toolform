import { useMemo, useState } from "react";
import { loadEnvelope } from "../lib/evidence";
import { LoaderError, loadTools, type LoadedTools } from "../lib/tools";

/* A textarea for tools as JSON (OpenAI, Anthropic, MCP or IR), validated as
 * it is typed, with the two sample sets. */

export interface ToolsValue {
  text: string;
  loaded: LoadedTools | null;
  error: string | null;
}

export function parseToolsText(text: string): ToolsValue {
  if (!text.trim()) return { text, loaded: null, error: null };
  try {
    return { text, loaded: loadTools(text), error: null };
  } catch (e) {
    return { text, loaded: null, error: e instanceof LoaderError ? e.message : String(e) };
  }
}

export async function sampleToolText(): Promise<string> {
  const env = await loadEnvelope("sample_renders");
  return env ? JSON.stringify(env.data.openai, null, 2) : "";
}

interface RenderCasesFile {
  data: { cases: { id: string; openai: unknown[]; ir: { tools: { name: string }[] } }[] };
}

export async function realToolsText(): Promise<string> {
  try {
    const r = await fetch(`${import.meta.env.BASE_URL}data/framework/render_cases.json`);
    const j = (await r.json()) as RenderCasesFile;
    const want = ["calculator", "github", "weather"];
    const out: unknown[] = [];
    for (const name of want) {
      const c = j.data.cases.find((x) => x.ir.tools.length === 1 && x.ir.tools[0].name === name);
      if (c) out.push(...c.openai);
    }
    return JSON.stringify(out, null, 2);
  } catch {
    return "";
  }
}

export function ToolsInput({ value, onChange, id = "fw-tools", rows = 14 }: { value: ToolsValue; onChange: (v: ToolsValue) => void; id?: string; rows?: number }) {
  const [busy, setBusy] = useState(false);
  const set = (text: string) => onChange(parseToolsText(text));
  const summary = useMemo(() => {
    if (!value.loaded) return null;
    const n = value.loaded.tools.length;
    return `${n} tool${n === 1 ? "" : "s"} read as ${value.loaded.kind}: ${value.loaded.tools.map((t) => t.name).slice(0, 6).join(", ")}${n > 6 ? ", ..." : ""}`;
  }, [value.loaded]);
  return (
    <div className="fw-field">
      <label htmlFor={id}>Tools (OpenAI, Anthropic, MCP or ToolForm IR JSON)</label>
      <div className="row" style={{ gap: 6 }}>
        <button type="button" className="fw-btn small" disabled={busy} onClick={async () => { setBusy(true); set(await sampleToolText()); setBusy(false); }}>
          Sample tool
        </button>
        <button type="button" className="fw-btn small" disabled={busy} onClick={async () => { setBusy(true); set(await realToolsText()); setBusy(false); }}>
          Three real tools
        </button>
        <button type="button" className="fw-btn small ghost" onClick={() => set("")}>
          Clear
        </button>
      </div>
      <textarea
        id={id}
        rows={rows}
        value={value.text}
        spellCheck={false}
        aria-invalid={!!value.error}
        aria-describedby={`${id}-status`}
        placeholder='[{"type": "function", "function": {"name": "get_forecast", "parameters": {...}}}]'
        onChange={(e) => set(e.target.value)}
      />
      <div id={`${id}-status`} className="hint" role="status">
        {value.error ? <span style={{ color: "var(--fw-danger)" }}>Not loaded: {value.error}</span> : summary ?? "Paste a tool file, or load a sample."}
      </div>
    </div>
  );
}
