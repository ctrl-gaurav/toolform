/* The advisor, ported from toolform.advisor.recommend.
 *
 * Deterministic and table-driven: it reads the study's tables, never a model.
 * The steps follow section (b) of docs/plans/framework_design.md one for one,
 * and the parity test checks every case in advisor_cases.json (same format,
 * protocol, basis and catalogue strategy; accuracy and range within 0.01).
 *
 * How the tables combine: the model's own value on the main grid (8 tools,
 * tier 3: its checkpoint row, anchor row or family row), moved by the shifts
 * the pooled tables measured for this tool count, this tier and this protocol.
 * Shifts combine in log-odds, so no estimate passes 0 or 100, and a tier gain
 * (measured at 8 tools only) is not applied at other tool counts. The study
 * measured each factor alone; this combination was not itself evaluated. The
 * range beside the point is the lowest and highest of the table values it
 * rests on. It is not a confidence interval.
 */

import type { CheckpointRow, Evidence, FamilyRow, Rule } from "./evidence";
import { CORE_FORMAT_LABELS, CORE_FORMATS, DEFAULT_PROTOCOL, isCoreFormat, renderFormat, type CoreFormat } from "./render";
import { CROSSING_PROTOCOLS, isCrossing, PROTOCOL_LABELS } from "./render/protocols";
import { estimateTokens, roundHalfEven } from "./tokens";
import { tierEstimate, type ToolIR } from "./tools";

export const RULES: Rule[] = ["main", "symmetric", "as_written"];
export const RULE_TEXT: Record<Rule, string> = {
  main: "each protocol's own parser; the text protocols re-nest a flat argument into its object",
  symmetric: "the same re-nesting repair applied under every protocol",
  as_written: "no repair: a reply that needed re-nesting is not accepted",
};
export const TWO_STAGE_FORMATS = ["names_then_schema", "names_then_schema_v2", "names_desc_then_schema", "oracle_then_schema"];
const TIE = 2.0;
const SWITCH_GAIN = 2.0;
const CONTEXT_SHARE = 0.5;
const THINKING_FAMILIES = ["qwen3", "qwen3.5", "qwen3.5-large"];

/** Log-odds of a percentage, bounded to 0.5 to 99.5 so it stays finite (logit in recommend.py). */
export function logit(p: number): number {
  const q = Math.min(Math.max(p, 0.5), 99.5) / 100;
  return Math.log(q / (1 - q));
}
export function expit(x: number): number {
  return 100 / (1 + Math.exp(-x));
}
/** A table value at the precision the table printed it: 77.7%, 67.52%. */
export function tablePct(x: number | null | undefined): string {
  if (x === null || x === undefined) return "n/a";
  const t = x.toFixed(2);
  return `${t.endsWith("0") ? t.slice(0, -1) : t}%`;
}

export interface Situation {
  model?: string | null;
  family?: string | null;
  params_b?: number | null;
  n_tools: number;
  tier: number;
  token_budget?: number | null;
  context_tokens?: number | null;
  objective: "accuracy" | "cost";
  price: "frontier_api" | "self_hosted";
  rule: Rule;
  protocol?: string | null;
  candidates?: string[] | null;
  third_party_tools: boolean;
}

export const DEFAULT_SITUATION: Situation = {
  model: null,
  family: null,
  params_b: null,
  n_tools: 8,
  tier: 3,
  token_budget: null,
  context_tokens: null,
  objective: "accuracy",
  price: "frontier_api",
  rule: "main",
  protocol: null,
  candidates: null,
  third_party_tools: false,
};

export interface ModelResolution {
  query: string | null;
  family: string | null;
  family_label: string | null;
  anchor: string | null;
  params_b: number | null;
  kind: string | null;
  context_tokens: number | null;
  matched_by: "anchor" | "checkpoint" | "zoo" | "pattern" | "family" | "none";
  checkpoint?: string | null;
}

export interface EvidenceRow {
  source: string;
  label: string;
  value: number | null;
  unit: string;
  interval: [number, number] | null;
  note: string;
}

export interface Alternative {
  format_id: string;
  format_name: string;
  protocol_id: string;
  expected_accuracy: number;
  schema_tokens: number | null;
  cost_per_request: number | null;
  score: number;
}

export interface CatalogueAdvice {
  strategy: "one_shot" | "retrieve" | "two_stage";
  reason: string;
  evidence: EvidenceRow[];
}

export interface GuardAdvice {
  action: "strip" | "drop_descriptions" | "none";
  reason: string;
  evidence: EvidenceRow[];
}

export interface Recommendation {
  format_id: string;
  format_name: string;
  protocol_id: string;
  protocol_name: string;
  expected_accuracy: number;
  interval: [number, number];
  interval_kind: "evidence_range";
  basis: string;
  rule: Rule;
  objective: string;
  schema_tokens: number | null;
  tokens_source: "rendered" | "study";
  cost_per_request: number | null;
  tied_with: string[];
  alternatives: Alternative[];
  catalogue: CatalogueAdvice;
  guard: GuardAdvice | null;
  measure_hint: string;
  surface: { format_id: string; predicted: number; note: string } | null;
  evidence: EvidenceRow[];
  explanation: string;
  warnings: string[];
  resolution: ModelResolution;
  situation: Situation;
  evidence_version: string;
  context_tokens: number | null;
  /** "mean of 7 checkpoints, 0.6 to 32B" when the family row is the basis. */
  basis_note: string;
}

/* ------------------------------------------------------------------ helpers */

const r2 = (x: number) => Math.round(x * 100) / 100;
export const fmtPct = (x: number | null | undefined, digits = 2) => (x === null || x === undefined ? "n/a" : `${x.toFixed(digits)}%`);
const fold = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");

function row(source: string, label: string, value: number | null, interval: [number, number] | null = null, note = "", unit = "%"): EvidenceRow {
  return { source, label, value, unit, interval, note };
}

export function formatLabel(ev: Evidence, f: string): string {
  return isCoreFormat(f) ? CORE_FORMAT_LABELS[f] : ev.formats[f]?.name ?? f;
}
export function formatName(ev: Evidence, f: string): string {
  return ev.formats[f]?.name ?? formatLabel(ev, f);
}
export function protocolName(p: string): string {
  return isCrossing(p) ? PROTOCOL_LABELS[p] : p;
}

/* ------------------------------------------------------------------ table reads */

/** Interpolated in log2(n) between the measured counts; clamped outside them. */
export function countAccuracy(ev: Evidence, f: string, n: number, table: "accuracy" | "empty" = "accuracy"): [number, boolean] {
  const counts = ev.tool_count.counts;
  const vals = ev.tool_count[table][f];
  if (!vals) return [NaN, false];
  if (n <= counts[0]) return [vals[0], n < counts[0]];
  const last = counts.length - 1;
  if (n >= counts[last]) return [vals[last], n > counts[last]];
  const x = Math.log2(n);
  for (let i = 0; i < last; i++) {
    const a = Math.log2(counts[i]);
    const b = Math.log2(counts[i + 1]);
    if (x >= a && x <= b) {
      const t = (x - a) / (b - a);
      return [vals[i] + t * (vals[i + 1] - vals[i]), false];
    }
  }
  return [vals[last], true];
}

export function tierAccuracy(ev: Evidence, f: string, tier: number): number {
  const i = ev.tiers.tiers.indexOf(tier);
  return ev.tiers.accuracy[f]?.[i] ?? NaN;
}

export function crossing(ev: Evidence, rule: Rule, f: string, p: string): number | null {
  return ev.protocol_crossing.rules[rule]?.cells[f]?.[p] ?? null;
}

export function coreMain(ev: Evidence, rule: Rule, f: string): number | null {
  const r = ev.core_main.rows.find((x) => x.format_id === f);
  return r ? r[rule] : null;
}

export function costOf(prompt: number, completion: number, cached: number, price: { input_per_m: number; cached_input_per_m: number; output_per_m: number }): number {
  return ((prompt - cached) * price.input_per_m + cached * price.cached_input_per_m + completion * price.output_per_m) / 1e6;
}

/* ------------------------------------------------------------------ model resolution */

function familyRows(ev: Evidence): FamilyRow[] {
  return ev.families.rows;
}

export function checkpointRow(ev: Evidence, id: string | null | undefined): CheckpointRow | undefined {
  if (!id) return undefined;
  const want = id.toLowerCase();
  return (ev.families.checkpoints ?? []).find((c) => c.id.toLowerCase() === want);
}

function familyLabel(ev: Evidence, family: string | null): string | null {
  if (!family) return null;
  const r = familyRows(ev).find((x) => x.family === family);
  return r?.label ?? ev.zoo.families[family]?.label ?? family;
}

function paramsFromId(id: string): number | null {
  let best: number | null = null;
  for (const m of id.toLowerCase().matchAll(/(\d+(?:\.\d+)?)b/g)) {
    const v = parseFloat(m[1]);
    if (best === null || v > best) best = v;
  }
  return best;
}

const EFFORT_PREFERENCE = ["medium", null, "low", "high"];

export function resolveModel(ev: Evidence, model: string | null | undefined, family?: string | null, paramsB?: number | null): ModelResolution {
  const query = model ?? null;
  const base: ModelResolution = { query, family: null, family_label: null, anchor: null, params_b: paramsB ?? null, kind: null, context_tokens: null, matched_by: "none" };
  const zooHit = query ? ev.zoo.models.find((m) => m.id.toLowerCase() === query.toLowerCase()) : undefined;
  const fillFromZoo = (r: ModelResolution) => {
    if (zooHit) {
      r.params_b = r.params_b ?? zooHit.params_b;
      r.kind = zooHit.kind;
      r.context_tokens = zooHit.max_model_len;
    }
    if (r.params_b === null && query) r.params_b = paramsFromId(query);
    return r;
  };
  if (family) {
    return fillFromZoo({ ...base, family, family_label: familyLabel(ev, family), matched_by: "family" });
  }
  if (!query) return base;
  const q = fold(query);
  const anchors = familyRows(ev).filter((r) => r.kind !== "open");
  // (a) the folded anchor name equals the query or is contained in it; the longest wins.
  const contained = anchors.filter((a) => q === fold(a.label) || q.includes(fold(a.label))).sort((a, b) => fold(b.label).length - fold(a.label).length);
  let anchor = contained[0];
  if (!anchor) {
    // (b) the name without its effort equals the query, preferring medium, then none, low, high.
    const bare = anchors.filter((a) => fold(a.label.replace(/\s*\([^)]*\)\s*$/, "")) === q);
    bare.sort((a, b) => EFFORT_PREFERENCE.indexOf(a.effort) - EFFORT_PREFERENCE.indexOf(b.effort));
    anchor = bare[0];
  }
  if (anchor) {
    return fillFromZoo({ ...base, anchor: anchor.label, family_label: anchor.label, matched_by: "anchor" });
  }
  const cp = checkpointRow(ev, query);
  if (cp) {
    return fillFromZoo({ ...base, family: cp.family, family_label: familyLabel(ev, cp.family), matched_by: "checkpoint", checkpoint: cp.id });
  }
  if (zooHit) {
    const fam = ev.zoo.aliases?.[zooHit.family] ?? (zooHit.family === "qwen3-quant" ? "qwen3" : zooHit.family);
    return fillFromZoo({ ...base, family: fam, family_label: familyLabel(ev, fam), matched_by: "zoo" });
  }
  const lower = query.toLowerCase();
  for (const [pattern, fam] of ev.zoo.patterns) {
    if (new RegExp(pattern).test(lower)) {
      const r = fillFromZoo({ ...base, matched_by: "pattern" });
      let f = fam;
      if (fam === "qwen3.5" && (r.params_b ?? 0) >= 100) f = "qwen3.5-large";
      r.family = f;
      r.family_label = familyLabel(ev, f);
      return r;
    }
  }
  return fillFromZoo(base);
}

/* ------------------------------------------------------------------ nearest rows */

/** The measured count nearest n in log2; a tie goes to the larger count (_nearest_count). */
function nearest(values: number[], n: number): number {
  const x = Math.log2(Math.max(1, n));
  let best = values[0];
  for (const v of values) {
    const d = Math.abs(x - Math.log2(v));
    const db = Math.abs(x - Math.log2(best));
    if (d < db - 1e-12 || (Math.abs(d - db) <= 1e-12 && v > best)) best = v;
  }
  return best;
}

function disclosureRow(ev: Evidence, n: number, arm: "names" | "names_desc" = "names_desc") {
  const rows = ev.disclosure.second_design.filter((r) => r.arm === arm);
  const at = nearest(Array.from(new Set(ev.disclosure.second_design.map((r) => r.n_tools))), n);
  return rows.find((r) => r.n_tools === at);
}

function overallRow(ev: Evidence, n: number) {
  const at = nearest(ev.tool_count.overall.map((r) => r.n_tools), n);
  return ev.tool_count.overall.find((r) => r.n_tools === at)!;
}

const signedPct = (v: number) => `${v >= 0 ? "+" : "-"}${Math.abs(v).toFixed(2)}%`;
const num = (x: number) => x.toLocaleString("en-US");

function disclosureSentence(d: { n_tools: number; minus_json: { value: number | null; interval: [number, number] | null } }): string {
  const v = d.minus_json.value ?? 0;
  const iv = d.minus_json.interval;
  const zero = !!(iv && iv[0] <= 0 && 0 <= iv[1]);
  const verb = zero
    ? `changed accuracy by ${signedPct(v)} against one shot, with an interval that includes zero`
    : v > 0
      ? `gained ${v.toFixed(2)}% over one shot`
      : `lost ${Math.abs(v).toFixed(2)}% against one shot`;
  return `at ${d.n_tools} tools, showing names and descriptions first ${verb} (tab_disclosure_v2)`;
}

/** The same sentences as catalogue_advice in recommend.py; the parity test compares them. */
export function catalogueAdvice(ev: Evidence, n: number, schemaTokens: number | null, context: number | null, forceTwoStage = false, budget: number | null = null): CatalogueAdvice {
  const overContext = !!(context && schemaTokens !== null && schemaTokens > CONTEXT_SHARE * context);
  const overBudget = !!(budget && schemaTokens !== null && schemaTokens > budget);
  const o = overallRow(ev, n);
  const d = disclosureRow(ev, n);
  const evidence: EvidenceRow[] = [];
  if (d) evidence.push(row("paper:tab_disclosure_v2", `names and descriptions first, minus one shot, at ${d.n_tools} tools`, d.minus_json.value, d.minus_json.interval, "53 checkpoints, three seeds"));
  if (forceTwoStage || n >= 64 || overContext || overBudget) {
    const size = schemaTokens !== null ? `about ${num(schemaTokens)} tokens` : "the tool block";
    let why: string;
    if (forceTwoStage && !(n >= 64 || overContext || overBudget)) why = "no core format fits the token budget";
    else if (overBudget && n < 64) why = `the tool block (${size}) is over the token budget of ${num(budget!)}`;
    else if (overContext && n < 64) why = `the tool block (${size}) would take more than half of the ${num(context!)}-token context window`;
    else why = `${n} tools is past the point where the one-shot block starts to fill the window`;
    const parts = [`Show the names first, then one schema, because ${why}.`];
    if (d) {
      const t = disclosureSentence(d);
      parts.push(t[0].toUpperCase() + t.slice(1) + ".");
    }
    if (o.empty > 0) {
      evidence.push(row("paper:tab_count", `turns with no answer at ${o.n_tools} tools`, o.empty, null, "pooled over the eight core formats"));
      parts.push(`At ${o.n_tools} tools, ${o.empty.toFixed(2)}% of one-shot turns returned nothing (tab_count).`);
    }
    return { strategy: "two_stage", reason: parts.join(" "), evidence };
  }
  if (n >= 32) {
    const whole = ev.tool_count.retrieval.find((r) => r.label === "128 shown whole")?.accuracy ?? null;
    const top8 = ev.tool_count.retrieval.find((r) => r.label === "top 8, BM25")?.accuracy ?? null;
    return {
      strategy: "retrieve",
      reason: `Retrieve the tools that match each request before showing them: on a 128-tool panel the top 8 by BM25 reached ${fmtPct(top8)} against ${fmtPct(whole)} for the whole panel (tab_count). Retrieval needs the request text, so it runs per request.`,
      evidence: [
        row("paper:tab_count", "128-tool panel shown whole", whole, null, "55 checkpoints"),
        row("paper:tab_count", "top 8 of the 128-tool panel by BM25", top8, null, "55 checkpoints; the gold tool is not forced in"),
        ...evidence,
      ],
    };
  }
  const reason = d
    ? `Show every tool at once; below 32 tools the block fits the window. For reference, ${disclosureSentence(d)}, at the price of a second model call per request.`
    : "Show every tool at once.";
  return { strategy: "one_shot", reason, evidence };
}

function guardAdvice(ev: Evidence, f: string): GuardAdvice {
  const inj = ev.injection.formats.find((r) => r.format_id === f);
  const trustS = ev.injection.trust.length ? -0.35 : null;
  const evidence = [
    row("paper:tab_pressure", `hidden instruction followed, ${formatLabel(ev, f)}`, inj?.hijack ?? null),
    row("paper:tab_injection_trust", "trust sentence in the system prompt, sentinel payload", trustS, [-1.49, 0.7]),
    row("paper:tab_injection_trust", "trust sentence in the system prompt, valid payload", 0.23, [-0.74, 1.23]),
    // The results section prints this range as -1.94 to +1.86; its sources read as below (see recommend.py).
    row("paper:tab_ladder", "accuracy effect of removing descriptions, all cells", null, null, "the ladder appendix: removing them costs 1.86%; tab_components4: adding them changes accuracy by -1.94%"),
    row("paper:tab_ladder", "Python stub without its docstring", -12.76),
  ];
  if (f === "json_minimal") {
    return { action: "none", reason: "The minimal schema shows no description; it followed no hijack in the study.", evidence };
  }
  const tail =
    f === "python_stub"
      ? " Do not use drop_descriptions with the Python stub: its docstring is its parameter documentation, and removing it cost 12.76%."
      : " Removing descriptions altogether cost 1.86% over all cells in the ladder appendix, so drop_descriptions is also an option.";
  return {
    action: "strip",
    reason: `Every format that shows descriptions let models follow a hidden instruction (${fmtPct(inj?.hijack)} for ${formatLabel(ev, f)}), and a trust sentence did not lower it. Strip flagged sentences before rendering.${tail}`,
    evidence,
  };
}

/* ------------------------------------------------------------------ surface */

function sigmoid(z: number): number {
  const c = Math.max(-60, Math.min(60, z));
  return 1 / (1 + Math.exp(-c));
}

export function surfacePredict(ev: Evidence, f: string, paramsB: number, n: number, tier: number): number | null {
  const s = ev.surface;
  if (!s || s.form !== "power_decay_in_tools") return null;
  const fit = s.fits[f];
  if (!fit) return null;
  const { a, b, gamma, delta, q } = fit.params;
  const logS = Math.log(Math.max(paramsB, 1e-3));
  const nn = Math.exp(Math.log(Math.max(1, n)));
  const c = s.complexity_by_tier[String(tier)] ?? 0.5;
  return sigmoid(a + b * logS - gamma * Math.pow(nn, q) - delta * c) * 100;
}

/** Smallest and largest open checkpoint of the study, in billions. */
export function openParamsRange(ev: Evidence): [number, number] | null {
  const sizes = (ev.families.checkpoints ?? []).map((c) => c.params_b).filter((x): x is number => typeof x === "number" && x > 0);
  return sizes.length ? [Math.min(...sizes), Math.max(...sizes)] : null;
}

/* ------------------------------------------------------------------ nested fields */

function* walkNames(params: ToolIR["params"], prefix: string, required: boolean): Generator<[string, string, boolean]> {
  for (const p of params) {
    const path = prefix ? `${prefix}.${p.name}` : p.name;
    const req = required && !!p.required;
    yield [path, p.name, req];
    yield* walkTypeNames(p.type, path, req);
  }
}
function* walkTypeNames(t: ToolIR["params"][number]["type"] | null | undefined, path: string, required: boolean): Generator<[string, string, boolean]> {
  if (!t) return;
  if (t.fields?.length) yield* walkNames(t.fields, path, required);
  if (t.item) yield* walkTypeNames(t.item, path + "[]", required);
  for (const u of t.union_of ?? []) yield* walkTypeNames(u, path, false);
}
const canon = (s: string) => Array.from(s.toLowerCase()).filter((ch) => /[\p{L}\p{N}]/u.test(ch)).join("");

/** Parameters whose name appears nowhere in a rendered block (hidden_fields in render.py). */
export function hiddenFields(tools: ToolIR[], text: string): { tool: string; path: string; required: boolean }[] {
  const words = new Set([...(text.match(/[\p{L}\p{N}_-]+/gu) ?? []), ...(text.match(/[\p{L}\p{N}_]+/gu) ?? [])].map(canon));
  const out: { tool: string; path: string; required: boolean }[] = [];
  for (const t of tools) for (const [path, name, req] of walkNames(t.params, "", true)) if (!words.has(canon(name))) out.push({ tool: t.name, path, required: req });
  return out;
}

/* ------------------------------------------------------------------ recommend */

interface Scored {
  f: string;
  p: string;
  expected: number;
  interval: [number, number];
  base: number;
  countCells: [number, number] | null;
  tierCells: [number, number] | null;
  tierDropped: boolean;
  protocolCells: [number, number] | null;
  keptDefault: [string, number] | null;
  tokens: number | null;
  cost: number | null;
  score: number;
  penalty: string[];
  rows: EvidenceRow[];
}

export function validateSituation(s: Situation): void {
  if (!Number.isInteger(s.n_tools) || s.n_tools < 1) throw new Error("n_tools must be a whole number of at least 1");
  if (!Number.isInteger(s.tier) || s.tier < 1 || s.tier > 5) throw new Error("tier must be 1, 2, 3, 4 or 5");
  if (!RULES.includes(s.rule)) throw new Error(`rule must be one of ${RULES.join(", ")}`);
  if (s.objective !== "accuracy" && s.objective !== "cost") throw new Error("objective must be accuracy or cost");
  if (s.token_budget !== null && s.token_budget !== undefined && s.token_budget <= 0) throw new Error("token_budget must be positive");
  if (s.params_b !== null && s.params_b !== undefined && !(Number.isFinite(s.params_b) && s.params_b > 0)) throw new Error("params_b must be a positive, finite number of billions");
  for (const c of s.candidates ?? []) if (TWO_STAGE_FORMATS.includes(c)) throw new Error(`${c} is a two-stage format; use toolform.catalogue.TwoStage`);
}

/** Mean output tokens of a protocol, from the tab_cost rows of the core formats whose default it is. */
export function completionTokens(ev: Evidence, p: string): number | null {
  const vals = (CORE_FORMATS as readonly string[]).filter((f) => DEFAULT_PROTOCOL[f as CoreFormat] === p).map((f) => ev.cost.rows.find((r) => r.format_id === f)?.completion).filter((x): x is number => typeof x === "number");
  return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
}

export function recommend(ev: Evidence, input: Partial<Situation>, tools?: ToolIR[] | null): Recommendation {
  const situation: Situation = { ...DEFAULT_SITUATION, ...input };
  if (tools && !tools.length) throw new Error("the toolset is empty; give at least one tool");
  if (tools && tools.length) {
    if (input.n_tools === undefined) situation.n_tools = tools.length;
    if (input.tier === undefined) situation.tier = tierEstimate(tools);
  }
  validateSituation(situation);
  const { rule, n_tools: n, tier: t } = situation;
  const warnings: string[] = [];
  const res = resolveModel(ev, situation.model, situation.family, situation.params_b);

  const anchorRow = res.anchor ? familyRows(ev).find((r) => r.label === res.anchor) : undefined;
  const cpRow = !anchorRow && res.checkpoint ? checkpointRow(ev, res.checkpoint) : undefined;
  const famRow = res.family ? familyRows(ev).find((r) => r.kind === "open" && r.family === res.family) : undefined;
  let basis = "pooled";
  let basisNote = "";
  if (rule === "main" && anchorRow) basis = `anchor:${anchorRow.label}`;
  else if (rule === "main" && cpRow) basis = `checkpoint:${cpRow.id}`;
  else if (rule === "main" && famRow) {
    basis = `family:${famRow.family}`;
    const rng = famRow.params_range;
    if (famRow.checkpoints) {
      const size = rng ? (rng[0] !== rng[1] ? `, ${rng[0]} to ${rng[1]}B` : `, ${rng[0]}B`) : "";
      basisNote = `mean of ${famRow.checkpoints} checkpoint${famRow.checkpoints === 1 ? "" : "s"}${size}`;
    }
  } else if ((anchorRow || famRow) && rule !== "main") warnings.push("family evidence exists only under the main rule; using the pooled table");
  const specific = basis !== "pooled";

  const candidates = Array.from(new Set((situation.candidates && situation.candidates.length ? situation.candidates : [...CORE_FORMATS]) as string[]));
  const [, clamped] = countAccuracy(ev, "xml_schema", n);
  if (clamped && n > 256) warnings.push("more than 256 tools is outside the measured range; the 256-tool value is used");
  if (rule !== "main" && (n !== 8 || t !== 3)) warnings.push(`the tool-count and tier shifts come from main-rule tables and are applied under the ${rule.replace("_", "-")} rule`);

  const price = ev.cost.prices[situation.price] ?? ev.cost.prices.frontier_api;

  const tokensAndCost = (f: string, p: string): [number | null, number | null] => {
    const crow = ev.cost.rows.find((r) => r.format_id === f);
    let tokens: number | null = null;
    if (tools && tools.length && isCoreFormat(f)) tokens = estimateTokens(renderFormat(tools, f as CoreFormat));
    else if (crow) tokens = roundHalfEven((crow.schema * n) / 8);
    if (!crow || tokens === null) return [tokens, null];
    const own = isCoreFormat(f) ? DEFAULT_PROTOCOL[f as CoreFormat] : null;
    const completion = p === own ? crow.completion : completionTokens(ev, p);
    if (completion === null) {
      if (situation.objective === "cost") warnings.push(`the study has no output length for ${p}; ${f} with it has no cost`);
      return [tokens, null];
    }
    const prompt = roundHalfEven(tokens + (crow.prompt - crow.schema));
    return [tokens, costOf(prompt, roundHalfEven(completion), price.schema_cached ? tokens : 0, price)];
  };

  const scoreOne = (f: string): Scored | null => {
    const core = isCoreFormat(f);
    const rows: EvidenceRow[] = [];
    const fl = formatLabel(ev, f);
    if (!core) {
      const m = ev.formats[f]?.measured?.call_exact ?? null;
      if (m === null) {
        warnings.push(`${f} has no measured row in the evidence; it is left out`);
        return null;
      }
      const p = situation.protocol ?? ev.formats[f]?.default_protocol ?? "json_object";
      rows.push(row("export:format_leaderboard", `${fl}, pooled over its cells`, m, null, "site export, not the paper's tables"));
      const [tokens, cost] = tokensAndCost(f, p);
      return { f, p, expected: m, interval: [m, m], base: m, countCells: null, tierCells: null, tierDropped: false, protocolCells: null, keptDefault: null, tokens, cost, score: 0, penalty: [], rows };
    }
    const pooled = coreMain(ev, rule, f)!;
    let base = pooled;
    if (basis.startsWith("anchor:") && anchorRow && anchorRow.accuracy[f] != null) {
      base = anchorRow.accuracy[f]!;
      rows.push(row("paper:tab_models_main", `${anchorRow.label}, ${fl}, 8 tools, tier 3, main rule`, base));
    } else if (basis.startsWith("checkpoint:") && cpRow && cpRow.accuracy[f] != null) {
      base = cpRow.accuracy[f];
      rows.push(row("paper:tab_models_full", `${cpRow.id}, ${fl}, 8 tools, tier 3, main rule`, base, null, "one checkpoint, three seeds of 50 requests per format"));
    } else if (basis.startsWith("family:") && famRow && famRow.accuracy[f] != null) {
      base = famRow.accuracy[f]!;
      rows.push(row("paper:tab_models_main", `${famRow.label} family, ${fl}, 8 tools, tier 3, main rule`, base));
    }
    rows.push(row("paper:tab_main", `${fl}, pooled, 8 tools, tier 3, ${rule} rule`, pooled, null, "51 checkpoints, seeds 0 to 2"));
    const [cn] = countAccuracy(ev, f, n);
    const [c8] = countAccuracy(ev, f, 8);
    const tt = tierAccuracy(ev, f, t);
    const t3 = tierAccuracy(ev, f, 3);
    const dn = logit(cn) - logit(c8);
    const dtRaw = logit(tt) - logit(t3);
    const dt = n === 8 || dtRaw < 0 ? dtRaw : 0;
    const tierDropped = dtRaw > 0 && dt === 0;
    if (n !== 8) rows.push(row("paper:tab_count_by_format", `${fl} at ${n} tools`, cn, null, `against ${c8.toFixed(2)} at 8 tools`));
    if (t !== 3) rows.push(row("paper:tab_tier_by_format", `${fl} at tier ${t}`, tt, null, `against ${t3.toFixed(2)} at tier 3, at 8 tools`));
    const d: string = DEFAULT_PROTOCOL[f as CoreFormat];
    let p: string = d;
    let dp = 0;
    let keptDefault: [string, number] | null = null;
    const crossD = isCrossing(d) ? crossing(ev, rule, f, d) : null;
    if (situation.protocol) {
      p = situation.protocol;
      if (p !== d) {
        const crossP = isCrossing(p) ? crossing(ev, rule, f, p) : null;
        if (crossP !== null && crossD !== null) dp = logit(crossP) - logit(crossD);
        else warnings.push(`no measurement pairs ${f} with ${p}`);
      }
    } else if (crossD !== null) {
      let best = d;
      let bestV = crossD;
      for (const q of CROSSING_PROTOCOLS) {
        const v = crossing(ev, rule, f, q);
        if (v !== null && v > bestV) {
          bestV = v;
          best = q;
        }
      }
      if (bestV - crossD >= SWITCH_GAIN) {
        if (specific) keptDefault = [best, bestV - crossD];
        else {
          p = best;
          dp = logit(bestV) - logit(crossD);
        }
      }
    }
    const cx = isCrossing(p) ? crossing(ev, rule, f, p) : null;
    if (cx !== null) rows.push(row("paper:tab_protocol", `${fl} with ${p}, ${rule} rule`, cx, null, "35 checkpoints, 8 tools, tier 3"));
    const lb = logit(base);
    const expected = expit(lb + dn + dt + dp);
    const views = [base, pooled, cn, tt, ...(cx !== null ? [cx] : []), expit(lb + dn), expit(lb + dt), expit(lb + dp), expected];
    const [tokens, cost] = tokensAndCost(f, p);
    return {
      f, p, expected, interval: [Math.min(...views), Math.max(...views)], base,
      countCells: [cn, c8], tierCells: [tt, t3], tierDropped,
      protocolCells: dp && cx !== null && crossD !== null ? [cx, crossD] : null,
      keptDefault, tokens, cost, score: 0, penalty: [], rows,
    };
  };

  const tokensSource: "rendered" | "study" = tools && tools.length ? "rendered" : "study";
  let scored = candidates.map(scoreOne).filter((x): x is Scored => x !== null);
  if (!scored.length) throw new Error("no candidate format has evidence to score");
  if (n !== 8 && t !== 3) {
    const dropped = scored.some((x) => x.tierDropped);
    warnings.push(`no table crossed the tool count and the tier: tier ${t} was measured at 8 tools and ${n} tools at tier 3${dropped ? "; a tier gain is therefore not applied at this count" : ""}`);
  }
  let forceTwoStage = false;
  if (situation.token_budget) {
    const budget = situation.token_budget;
    const over = scored.filter((s) => s.tokens !== null && s.tokens > budget);
    if (over.length) warnings.push(`over the token budget of ${num(budget)}: ${over.map((s) => s.f).join(", ")}`);
    scored = scored.filter((s) => !(s.tokens !== null && s.tokens > budget));
    if (!scored.length) {
      const last = scoreOne("json_minimal")!;
      scored = [last];
      forceTwoStage = true;
      warnings.push(last.tokens !== null && last.tokens > budget ? "no core format fits the budget; use two-stage disclosure" : "only the minimal schema fits the budget; two-stage disclosure keeps full schemas");
    }
  }
  const context = situation.context_tokens ?? res.context_tokens ?? null;
  if (context) {
    const tooBig = scored.filter((s) => s.tokens !== null && s.tokens > CONTEXT_SHARE * context);
    for (const s of tooBig) s.penalty.push("context");
    if (tooBig.length) warnings.push(`over half of the ${num(context)}-token context window: ${tooBig.map((s) => s.f).join(", ")}; ranked last${situation.context_tokens ? "" : " (the window is the model zoo's max_model_len)"}`);
  }
  if (tools && tools.length) {
    const hidden = new Map<string, string[]>();
    for (const s of scored) {
      if (!isCoreFormat(s.f)) continue;
      const h = hiddenFields(tools, renderFormat(tools, s.f as CoreFormat)).filter((x) => x.required).map((x) => `${x.tool}.${x.path}`);
      if (h.length) {
        hidden.set(s.f, h);
        s.penalty.push("hidden");
      }
    }
    if (hidden.size) {
      const [first] = hidden.values();
      warnings.push(`${[...hidden.keys()].join(", ")} hide required nested fields of these tools (${first.slice(0, 4).join(", ")}); ranked after the formats that show them`);
    }
  }
  for (const s of scored) s.score = situation.objective === "cost" ? (s.cost ? s.expected / s.cost : -Infinity) : s.expected;
  if (situation.objective === "cost" && scored.every((s) => s.score === -Infinity)) {
    warnings.push("no candidate has a cost in the study's table; ranking by accuracy");
    for (const s of scored) s.score = s.expected;
  }
  const order = new Map(candidates.map((c, i) => [c, i]));
  const ranked = [...scored].sort((a, b) => Number(a.penalty.length > 0) - Number(b.penalty.length > 0) || b.score - a.score || (order.get(a.f) ?? 99) - (order.get(b.f) ?? 99));
  const win = ranked[0];
  const rest = win.penalty.length ? ranked.slice(1) : ranked.slice(1).filter((s) => !s.penalty.length);
  const tied = rest.filter((s) => (situation.objective === "cost" ? win.score > 0 && s.score >= win.score * 0.98 : win.expected - s.expected <= TIE)).map((s) => s.f);
  if (win.keptDefault) warnings.push(`the pooled protocol table has ${win.f} ${win.keptDefault[1].toFixed(1)} points higher with ${win.keptDefault[0]} than with ${win.p}, but that was not measured on this model, so ${win.p} is kept; pass protocol=${win.keptDefault[0]} to use it`);

  const catalogue = catalogueAdvice(ev, n, win.tokens, context, forceTwoStage, situation.token_budget ?? null);
  const guardA = situation.third_party_tools ? guardAdvice(ev, win.f) : null;
  if (rule === "main" && (win.p === "xml_call" || win.p === "nl_intent")) {
    warnings.push(`${win.p} is a text protocol: under the main rule its parser re-nests a flat argument, and a human check judged that repair wrong on 12.5% [8.6, 17.8] of the turns it touched; the symmetric rule applies the same repair to every protocol`);
  }
  let surface: Recommendation["surface"] = null;
  const pb = res.params_b ?? situation.params_b ?? null;
  if (pb) {
    const rng = openParamsRange(ev);
    if (rng && !(rng[0] <= pb && pb <= rng[1])) warnings.push(`${pb}B is outside the open checkpoints the surface was fitted on (${rng[0]} to ${rng[1]}B); the fitted surface is left out`);
    else {
      const pred = surfacePredict(ev, win.f, pb, n, t);
      if (pred !== null) surface = { format_id: win.f, predicted: r2(pred), note: "held-out R² 0.219; shown for extrapolation only" };
    }
  }
  const thinkingOff = !!res.family && THINKING_FAMILIES.includes(res.family);

  const alternatives: Alternative[] = ranked.slice(1).map((s) => ({
    format_id: s.f,
    format_name: formatName(ev, s.f),
    protocol_id: s.p,
    expected_accuracy: r2(s.expected),
    schema_tokens: s.tokens,
    cost_per_request: s.cost,
    score: r2(s.score),
  }));

  const rec: Recommendation = {
    format_id: win.f,
    format_name: formatName(ev, win.f),
    protocol_id: win.p,
    protocol_name: protocolName(win.p),
    expected_accuracy: r2(win.expected),
    interval: [r2(win.interval[0]), r2(win.interval[1])],
    interval_kind: "evidence_range",
    basis: isCoreFormat(win.f) ? basis : "pooled",
    rule,
    objective: situation.objective,
    schema_tokens: win.tokens,
    tokens_source: tokensSource,
    cost_per_request: win.cost,
    tied_with: tied,
    alternatives,
    catalogue,
    guard: guardA,
    measure_hint:
      "If you can call the model, run toolform ab-test. In the study, measuring eight formats on the target model reached 69.18%, against 64.35% for the fitted rule, 65.02% for always XML and 57.97% for the JSON Schema default (tab:selection)." +
      (thinkingOff ? " Pass --no-thinking: this family's chat template thinks by default, the study turned it off, and a reply cut off inside its thinking counts as wrong." : ""),
    surface,
    evidence: win.rows,
    explanation: "",
    warnings: Array.from(new Set(warnings)),
    resolution: res,
    situation,
    evidence_version: ev.version,
    context_tokens: context,
    basis_note: isCoreFormat(win.f) ? basisNote : "",
  };
  rec.explanation = explain(ev, rec, win, ranked);
  return rec;
}

/* ------------------------------------------------------------------ explanation */

export function describeBasis(res: ModelResolution, basis: string, note = ""): string {
  if (basis.startsWith("anchor:")) return `the anchor model ${basis.slice(7)}`;
  if (basis.startsWith("checkpoint:")) return `the checkpoint ${basis.slice(11)}, measured on its own`;
  if (basis.startsWith("family:")) return `the ${res.family_label ?? basis.slice(7)} family${note ? ` (${note})` : ""}`;
  return "all 51 checkpoints pooled";
}

function explain(ev: Evidence, rec: Recommendation, win: Scored, ranked: Scored[]): string {
  const fl = formatLabel(ev, rec.format_id);
  const s = rec.situation;
  const parts: string[] = [];
  const ruleName = rec.rule.replace("_", " ");
  if (rec.basis === "pooled") {
    parts.push(`Pooled over 51 checkpoints at 8 tools and tier 3, ${fl} scored ${tablePct(win.base)} under the ${ruleName} rule (tab_main).`);
  } else {
    const src = rec.basis.startsWith("checkpoint:") ? "tab_models_full" : "tab_models_main";
    const best = ranked.every((x) => win.base >= x.base) ? "the most accurate of the eight core formats" : "one of the eight core formats";
    parts.push(`For ${describeBasis(rec.resolution, rec.basis, rec.basis_note)} at 8 tools and tier 3, ${fl} was ${best}: ${tablePct(win.base)} under the main rule (${src}).`);
  }
  const ratio = ev.protocol_crossing.ratios[rec.rule];
  let pSentence = `Over 35 checkpoints the answer protocol changed accuracy ${ratio.toFixed(2)} times as much as the format under this rule (tab_protocol)`;
  if (win.protocolCells) pSentence += `, and ${fl} scored ${tablePct(win.protocolCells[0])} with ${rec.protocol_id} against ${tablePct(win.protocolCells[1])} with its own protocol`;
  parts.push(pSentence + ".");
  const shifts: string[] = [];
  if (win.countCells && s.n_tools !== 8) shifts.push(`the count table has ${fl} at ${win.countCells[0].toFixed(2)}% for ${s.n_tools} tools against ${win.countCells[1].toFixed(2)}% at 8 (tab_count_by_format)`);
  if (win.tierCells && s.tier !== 3) shifts.push(`the tier table has it at ${tablePct(win.tierCells[0])} for tier ${s.tier} against ${tablePct(win.tierCells[1])} at tier 3${win.tierDropped ? " (a gain measured at 8 tools, so not applied here)" : ""} (tab_tier_by_format)`);
  if (shifts.length) parts.push(`Moving that to this situation in log-odds: ${shifts.join("; ")}.`);
  parts.push(
    `With ${rec.protocol_id}, at ${s.n_tools} tools and tier ${s.tier}, the expected accuracy is ${fmtPct(rec.expected_accuracy)} (range ${rec.interval[0].toFixed(2)} to ${rec.interval[1].toFixed(2)} across the table values it rests on). The study measured each factor alone; this combination was not itself evaluated.`,
  );
  if (rec.schema_tokens !== null) {
    parts.push(`The tool block costs about ${num(rec.schema_tokens)} tokens (${rec.tokens_source === "rendered" ? "estimated as characters / 4 from your tools" : "scaled from the study's cost table at 8 tools"}).`);
  }
  if (rec.tied_with.length) {
    const cheapest = [win, ...ranked.filter((x) => rec.tied_with.includes(x.f))].filter((x) => x.tokens !== null).sort((a, b) => (a.tokens ?? 0) - (b.tokens ?? 0))[0];
    const tiedText = rec.tied_with.map((f) => formatLabel(ev, f)).join(", ");
    parts.push(
      cheapest && cheapest.f !== win.f
        ? `${tiedText} ${rec.tied_with.length === 1 ? "is" : "are"} within ${TIE.toFixed(1)} of it; the cheapest of them is ${formatLabel(ev, cheapest.f)}.`
        : `${tiedText} ${rec.tied_with.length === 1 ? "is" : "are"} within ${TIE.toFixed(1)} of it.`,
    );
  }
  parts.push(rec.catalogue.reason);
  if (rec.guard) parts.push(rec.guard.reason.split(". ")[0] + ".");
  return parts.join(" ");
}

/** The "Copy Python" and "Copy CLI" strings for a situation. */
export function situationArgs(s: Situation): [string, string, string][] {
  const out: [string, string, string][] = [];
  if (s.model) out.push(["model", JSON.stringify(s.model), `--model ${s.model}`]);
  if (s.family) out.push(["family", JSON.stringify(s.family), `--family ${s.family}`]);
  if (s.params_b) out.push(["params_b", String(s.params_b), `--params-b ${s.params_b}`]);
  out.push(["n_tools", String(s.n_tools), `--n-tools ${s.n_tools}`]);
  out.push(["tier", String(s.tier), `--tier ${s.tier}`]);
  if (s.token_budget) out.push(["token_budget", String(s.token_budget), `--budget ${s.token_budget}`]);
  if (s.context_tokens) out.push(["context_tokens", String(s.context_tokens), `--context ${s.context_tokens}`]);
  if (s.objective !== "accuracy") out.push(["objective", JSON.stringify(s.objective), `--objective ${s.objective}`]);
  if (s.objective === "cost" && s.price !== "frontier_api") out.push(["price", JSON.stringify(s.price), `--price ${s.price}`]);
  if (s.rule !== "main") out.push(["rule", JSON.stringify(s.rule), `--rule ${s.rule}`]);
  if (s.protocol) out.push(["protocol", JSON.stringify(s.protocol), `--protocol ${s.protocol}`]);
  if (s.third_party_tools) out.push(["third_party_tools", "True", "--third-party"]);
  return out;
}

export { CORE_FORMATS, type CoreFormat };
