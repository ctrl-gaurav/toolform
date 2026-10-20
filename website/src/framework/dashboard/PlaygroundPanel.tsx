import { Fragment, useEffect, useMemo, useState } from "react";
import { api, useApi, type ParseResponse, type RenderResponse } from "../lib/api";
import { useEvidence } from "../lib/evidence";
import { CORE_FORMATS, DEFAULT_PROTOCOL, isCoreFormat, protocolInstructions, renderFormat, type RenderOptions } from "../lib/render";
import { CROSSING_PROTOCOLS, isCrossing, systemPrompt } from "../lib/render/protocols";
import { estimateTokens } from "../lib/tokens";
import { Callout } from "../ui/Callout";
import { CodeBlock } from "../ui/CodeBlock";
import { Field } from "../ui/Field";
import { FormatGrid } from "./FormatGrid";
import { parseToolsText, sampleToolText, ToolsInput, type ToolsValue } from "./ToolsInput";

const OPTION_LABELS: [keyof RenderOptions, string][] = [
  ["descriptions", "descriptions"],
  ["constraints", "constraints"],
  ["defaults", "defaults"],
  ["returns", "returns"],
  ["minify", "minify"],
];

function SampleFormats() {
  const { data } = useEvidence("sample_renders");
  const [family, setFamily] = useState("all");
  const [open, setOpen] = useState<string | null>(null);
  const [all, setAll] = useState(false);
  if (!data) return null;
  const rows = data.renders.filter((r) => !r.two_stage).sort((a, b) => a.tokens_estimate - b.tokens_estimate);
  const families = Array.from(new Set(rows.map((r) => r.family))).sort();
  const filtered = rows.filter((r) => family === "all" || r.family === family);
  const shown = all ? filtered : filtered.slice(0, 20);
  return (
    <section className="fw-section" style={{ paddingTop: 56 }} aria-labelledby="every-format">
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
        <div>
          <h2 id="every-format" style={{ fontSize: 22 }}>
            Every format for the sample tool
          </h2>
          <p className="muted" style={{ fontSize: 14 }}>
            The {rows.length} study formats rendering legal_draft_v3, sorted by tokens. Rendered by the Python SDK; formats we invented are marked (novel).
          </p>
        </div>
        <div className="fw-field" style={{ margin: 0, minWidth: 200 }}>
          <label htmlFor="fw-fam">Family</label>
          <select id="fw-fam" value={family} onChange={(e) => setFamily(e.target.value)}>
            <option value="all">all families</option>
            {families.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="tablewrap">
        <table>
          <thead>
            <tr>
              <th>format</th>
              <th>family</th>
              <th>default protocol</th>
              <th className="num">tokens</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <Fragment key={r.format_id}>
                <tr className={open === r.format_id ? "hl" : undefined}>
                  <td>
                    {r.format_id} {r.novel && <span className="faint">(novel)</span>}
                    <div className="faint" style={{ fontSize: 12 }}>{r.name}</div>
                  </td>
                  <td>{r.family}</td>
                  <td className="mono" style={{ fontSize: 12.5 }}>{r.default_protocol}</td>
                  <td className="num">{r.tokens_estimate.toLocaleString("en-US")}</td>
                  <td>
                    <button type="button" className="fw-copy" aria-expanded={open === r.format_id} onClick={() => setOpen(open === r.format_id ? null : r.format_id)}>
                      {open === r.format_id ? "Hide" : "Show"}
                    </button>
                  </td>
                </tr>
                {open === r.format_id && (
                  <tr>
                    <td colSpan={5} style={{ whiteSpace: "normal" }}>
                      <CodeBlock code={r.text} title={r.format_id} tall />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      {filtered.length > 20 && (
        <div style={{ marginTop: 12 }}>
          <button type="button" className="fw-btn small" aria-expanded={all} onClick={() => setAll((a) => !a)}>
            {all ? "Show the first 20" : `Show all ${filtered.length}`}
          </button>
        </div>
      )}
    </section>
  );
}

function ParsePanel({ tools, protocol }: { tools: ToolsValue; protocol: string }) {
  const { base, status } = useApi();
  const [text, setText] = useState("");
  const [rule, setRule] = useState("main");
  const [out, setOut] = useState<ParseResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    if (!tools.loaded) return;
    setBusy(true);
    setErr(null);
    try {
      setOut(await api.parse(base, { tools: { source: "auto", payload: JSON.parse(tools.text) }, text, protocol, rule, validate: true, lenient_fallback: false }));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="fw-card" style={{ marginTop: 24 }} aria-labelledby="parse-h">
      <h2 id="parse-h" style={{ fontSize: 18 }}>
        Parse a reply
      </h2>
      {status !== "online" ? (
        <p className="muted" style={{ marginBottom: 0 }}>
          Parsing runs in the API: start <code>toolform serve</code> and press Retry above. The study's 31 parsers and three grading rules are Python; the browser does
          not reimplement them.
        </p>
      ) : (
        <>
          <Field label={`A model's reply, parsed as ${protocol}`}>
            <textarea rows={6} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
          </Field>
          <div className="row">
            <select value={rule} onChange={(e) => setRule(e.target.value)} aria-label="Grading rule" style={{ width: 180 }}>
              <option value="main">main rule</option>
              <option value="symmetric">symmetric rule</option>
              <option value="as_written">as written</option>
            </select>
            <button type="button" className="fw-btn small primary" onClick={run} disabled={busy || !tools.loaded || !text.trim()}>
              Parse
            </button>
          </div>
          {err && <p style={{ color: "var(--fw-danger)" }}>{err}</p>}
          {out && <CodeBlock code={JSON.stringify(out, null, 2)} lang="json" title={`ok: ${out.ok}, strict parse: ${out.parsed_strict}, format compliant: ${out.format_compliant}`} tall />}
        </>
      )}
    </section>
  );
}

export function PlaygroundPanel() {
  const { base, status } = useApi();
  const formats = useEvidence("formats").data;
  const protocols = useEvidence("protocols").data;
  const coreMain = useEvidence("core_main").data;
  const [tools, setTools] = useState<ToolsValue>(parseToolsText(""));
  const [format, setFormat] = useState<string>("xml_schema");
  const [protocol, setProtocol] = useState<string>("");
  const [request, setRequest] = useState("Draft a 12-month contract with Holt & Vane worth 240000, status signed.");
  const [opts, setOpts] = useState<Partial<RenderOptions>>({});
  const [remote, setRemote] = useState<RenderResponse | null>(null);
  const [remoteErr, setRemoteErr] = useState<string | null>(null);

  useEffect(() => {
    sampleToolText().then((t) => t && setTools((cur) => (cur.text ? cur : parseToolsText(t))));
  }, []);

  const online = status === "online";
  const effectiveProtocol = protocol || (isCoreFormat(format) ? DEFAULT_PROTOCOL[format] : formats?.[format]?.default_protocol ?? "json_object");
  const local = useMemo(() => {
    if (!tools.loaded || !isCoreFormat(format)) return null;
    try {
      const block = renderFormat(tools.loaded.tools, format, opts);
      const instructions = isCrossing(effectiveProtocol) ? protocolInstructions(effectiveProtocol) : protocols?.[effectiveProtocol]?.instructions ?? "";
      return { block, instructions, system: systemPrompt({ toolBlock: block, instructions }) };
    } catch (e) {
      return { block: `Render failed: ${(e as Error).message}`, instructions: "", system: "" };
    }
  }, [tools.loaded, format, opts, effectiveProtocol, protocols]);

  useEffect(() => {
    setRemote(null);
    setRemoteErr(null);
    if (!online || !tools.loaded || isCoreFormat(format)) return;
    let alive = true;
    api
      .render(base, { tools: { source: "auto", payload: JSON.parse(tools.text) }, format, protocol: protocol || null, options: opts, request: request || null })
      .then((r) => alive && setRemote(r))
      .catch((e) => alive && setRemoteErr((e as Error).message));
    return () => {
      alive = false;
    };
  }, [online, base, tools.text, tools.loaded, format, protocol, opts, request]);

  const studyFormats = Object.values(formats ?? {}).filter((f) => f.in_study);
  const block = local?.block ?? remote?.tool_block ?? "";
  const instructions = local?.instructions ?? remote?.instructions ?? "";
  const system = local?.system ?? remote?.system_prompt ?? "";
  const protocolChoices = online ? Object.keys(protocols ?? {}) : [...CROSSING_PROTOCOLS];

  return (
    <div style={{ paddingTop: 32 }}>
      <div className="fw-split">
        <aside className="fw-card" aria-label="Inputs">
          <ToolsInput value={tools} onChange={setTools} rows={12} />
          <Field label="Format" hint={online ? "All 129 study formats: the eight core ones render in the browser, the rest through the API." : "The eight core formats render in the browser. Start toolform serve for the other 121."}>
            <select value={format} onChange={(e) => setFormat(e.target.value)}>
              <optgroup label="The eight core formats">
                {CORE_FORMATS.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </optgroup>
              {online && (
                <optgroup label="Every other study format (API)">
                  {studyFormats
                    .filter((f) => !isCoreFormat(f.id))
                    .map((f) => (
                      <option key={f.id} value={f.id}>
                        {f.id}
                        {f.novel ? " (novel)" : ""}
                      </option>
                    ))}
                </optgroup>
              )}
            </select>
          </Field>
          <Field label="Answer protocol" hint={online ? "Any of the 31." : "The five protocols of the crossing experiment; the API offers all 31."}>
            <select value={protocol} onChange={(e) => setProtocol(e.target.value)}>
              <option value="">the format's default ({isCoreFormat(format) ? DEFAULT_PROTOCOL[format] : effectiveProtocol})</option>
              {protocolChoices.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </Field>
          <fieldset className="fw-field" style={{ border: 0, padding: 0 }}>
            <legend className="flabel" style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
              Rendering options
            </legend>
            <div className="row" style={{ gap: 14 }}>
              {OPTION_LABELS.map(([k, label]) => {
                const on = (opts[k] as boolean | undefined) ?? k !== "minify";
                return (
                  <label key={k} className="check">
                    <input type="checkbox" checked={on} onChange={(e) => setOpts((o) => ({ ...o, [k]: e.target.checked }))} />
                    {label}
                  </label>
                );
              })}
            </div>
          </fieldset>
          <Field label="Request (for the messages)">
            <input type="text" value={request} onChange={(e) => setRequest(e.target.value)} />
          </Field>
        </aside>
        <section className="fw-stack" aria-label="Rendered prompt" style={{ gap: 16 }}>
          {!tools.loaded && <Callout>Load tools on the left to render them.</Callout>}
          {tools.loaded && !isCoreFormat(format) && !online && <Callout tone="warn">This format renders through the API. Start toolform serve and press Retry.</Callout>}
          {remoteErr && <Callout tone="danger">The API could not render it: {remoteErr}</Callout>}
          {block && (
            <>
              <div className="row" style={{ gap: 24 }}>
                <div className="fw-stat">
                  <div className="v" style={{ fontSize: 30 }}>{estimateTokens(block).toLocaleString("en-US")}</div>
                  <div className="k">tokens in the tool block, estimated as characters / 4</div>
                </div>
                <div className="fw-stat">
                  <div className="v" style={{ fontSize: 30 }}>{block.length.toLocaleString("en-US")}</div>
                  <div className="k">characters</div>
                </div>
                <div className="fw-stat">
                  <div className="v" style={{ fontSize: 30 }}>{estimateTokens(system).toLocaleString("en-US")}</div>
                  <div className="k">tokens in the whole system prompt</div>
                </div>
              </div>
              <CodeBlock code={block} title={`tool block: ${format}${remote ? " (from the API)" : ""}`} tall />
              <CodeBlock code={instructions} title={`answer instruction: ${effectiveProtocol}`} wrap />
              <details className="fw-card" style={{ padding: 16 }}>
                <summary style={{ cursor: "pointer", fontWeight: 600 }}>The system prompt and the messages, as the study assembled them</summary>
                <div style={{ marginTop: 12 }}>
                  <CodeBlock code={JSON.stringify([{ role: "system", content: system }, { role: "user", content: request }], null, 2)} lang="json" title="messages" wrap tall />
                </div>
              </details>
            </>
          )}
        </section>
      </div>

      <ParsePanel tools={tools} protocol={effectiveProtocol} />

      {tools.loaded && (
        <section className="fw-section" style={{ paddingTop: 56 }} aria-labelledby="all-eight">
          <h2 id="all-eight" style={{ fontSize: 22 }}>
            All eight side by side
          </h2>
          <p className="muted" style={{ fontSize: 14 }}>
            Your tools in the eight core formats, cheapest first. The accuracy is each format's main-grid value in the study (8 tools, tier 3, 51 checkpoints), not a
            prediction for your tools.
          </p>
          <FormatGrid tools={tools.loaded.tools} options={opts} coreMain={coreMain?.rows ?? []} />
        </section>
      )}

      <SampleFormats />
    </div>
  );
}
