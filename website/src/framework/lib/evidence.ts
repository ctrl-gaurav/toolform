/* The evidence files, typed, and a hook that loads them.
 *
 * website/public/data/framework/*.json is a byte copy of the package's
 * toolform/advisor/data/*.json (npm run sync), so the dashboard, the CLI and
 * the HTTP API read the same numbers. Every file carries the same envelope;
 * the schemas are section (d) of docs/plans/framework_design.md.
 */

import { useEffect, useState } from "react";
import type { ToolIR } from "./tools";

export interface Envelope<T> {
  schema_version: number;
  name: string;
  source: string[];
  description: string;
  conditions: Record<string, unknown>;
  source_note?: string;
  data: T;
}

export interface ManifestFile {
  name: string;
  path: string;
  sha256: string;
  bytes: number;
  source: string[];
}
export interface Manifest {
  evidence_version: string;
  built_at: string;
  toolform_version: string;
  source_note?: string;
  files: ManifestFile[];
  sources: { path: string; sha256: string }[];
  notes: string[];
}

export interface Fact {
  id: string;
  value: number;
  interval: [number, number] | null;
  unit: string;
  text: string;
  source: string;
}

export interface Measured {
  source: string;
  as_of: string;
  call_exact: number | null;
  tool_correct: number | null;
  schema_valid: number | null;
  parse_strict: number | null;
  format_compliant: number | null;
  mean_schema_tokens: number | null;
  acc_per_1k_tokens: number | null;
  n_cells: number | null;
}
export interface FormatEntry {
  id: string;
  name: string;
  family: string;
  description: string;
  default_protocol: string;
  novel: boolean;
  real_world_origin: string;
  lossy: boolean;
  tags: string[];
  core: boolean;
  two_stage: boolean;
  in_study: boolean;
  measured: Measured | null;
}
export interface ProtocolEntry {
  id: string;
  name: string;
  description: string;
  novel: boolean;
  in_crossing: boolean;
  instructions?: string;
}

export interface Contrast {
  value: number | null;
  interval: [number, number] | null;
}
export interface CoreMainRow {
  format_id: string;
  protocol_id: string;
  main: number;
  symmetric: number;
  as_written: number;
  rank_main: number;
  rank_symmetric: number;
  rank_as_written: number;
  minus_json_main: Contrast;
  minus_json_as_written: Contrast;
  real_accuracy: number | null;
  real_minus_json: Contrast;
}
export interface FamilyRow {
  label: string;
  family: string | null;
  kind: "open" | "anchor_open" | "anchor_proprietary";
  effort: string | null;
  checkpoints: number;
  params: string | null;
  accuracy: Record<string, number | null>;
  mean: number;
  spread: number;
  best_format: string | null;
  /** Smallest and largest checkpoint of an open family, in billions (tab_models_full). */
  params_range?: [number, number] | null;
}
/** One open-weight checkpoint's own row of tab_models_full. */
export interface CheckpointRow {
  id: string;
  family: string;
  family_label: string;
  params_b: number | null;
  accuracy: Record<string, number>;
  mean: number | null;
  spread: number | null;
  best_format: string;
}
export type Rule = "main" | "symmetric" | "as_written";
export interface CrossingRule {
  cells: Record<string, Record<string, number>>;
  row_mean: Record<string, number>;
  col_mean: Record<string, number>;
}
export interface Crossing {
  protocols: string[];
  rules: Record<Rule, CrossingRule>;
  ratios: Record<Rule, number>;
  checkpoints: number;
  cells: number;
}
export interface ToolCount {
  counts: number[];
  accuracy: Record<string, number[]>;
  empty: Record<string, number[]>;
  overall: { n_tools: number; strict: number; symmetric: number; exact_tool: number; twin: number; behavioural: number; end_state: number; empty: number }[];
  retrieval: { label: string; accuracy: number; gain?: number }[];
  empty_filtered_256: number | null;
}
export interface Tiers {
  tiers: number[];
  accuracy: Record<string, number[]>;
  empty: Record<string, number[]>;
  definitions: Record<string, string>;
}
export interface CostRow {
  format_id: string;
  accuracy: number;
  schema: number;
  prompt: number;
  completion: number;
  total: number;
  acc_per_1k: number;
  acc_per_price_a: number;
  acc_per_price_b: number;
}
export interface PriceVector {
  input_per_m: number;
  cached_input_per_m: number;
  output_per_m: number;
  schema_cached: boolean;
}
export interface Cost {
  rows: CostRow[];
  prices: Record<string, PriceVector>;
  n_tools: number;
  /** The package writes points and frontier at the top level; the bootstrap nested them. Both are read. */
  points?: CostPoint[];
  frontier?: CostPoint[] | { source: string; points: CostPoint[]; frontier: CostPoint[] };
}
export interface CostPoint {
  format_id: string;
  tokens: number;
  call_exact: number | null;
}
export interface Injection {
  formats: { format_id: string; hijack: number; decoy: number | null; control: number; minus_nl: Contrast; acc_control: number; acc_hijack: number; drop: number }[];
  once: { format_id: string; hijack: number; minus_nl: Contrast; acc_control: number; acc_hijack: number; drop: number }[];
  trust: { payload: string; trust_line: boolean; format_id: string; followed: number; interval: [number, number] | null; control: number; acc_control: number; acc_hijack: number; credited_valid: number }[];
}
export interface Disclosure {
  first_design: { n_tools: number; reduced: number; twin_credit: number; json: number; minus_json: number }[];
  second_design: { n_tools: number; arm: "names" | "names_desc" | "oracle"; checkpoints: number; selected: number; twin: number; failed: number; exact_tool: number; call: number; json: number; minus_json: Contrast; selection_tokens: number }[];
}
export interface SelectionRow {
  family_label: string;
  family: string;
  conditions: number;
  always_json: number;
  always_xml: number;
  lookup: number;
  measure_eight: number;
  fitted_rule: number;
  oracle: number;
}
export interface Selection {
  rows: SelectionRow[];
  mean: Omit<SelectionRow, "family_label" | "family">;
  cells: number;
}
export interface Ladder {
  rungs: { format_id: string; shows: string; accuracy: number }[];
  gap: Contrast;
  names_only_by_count: { n_tools: number; pairs: number; names_call: number; json_call: number; gap: Contrast; names_name: number; json_name: number }[];
}
export interface ZooModel {
  id: string;
  family: string;
  params_b: number | null;
  kind: string;
  open: boolean;
  max_model_len: number | null;
  in_study: boolean;
}
export interface Zoo {
  models: ZooModel[];
  families: Record<string, { label: string; n_models: number }>;
  patterns: [string, string][];
  /** Zoo family keys that map to another family's evidence, e.g. qwen3-quant to qwen3. */
  aliases?: Record<string, string>;
}
export interface Surface {
  form: string;
  param_names: string[];
  complexity_by_tier: Record<string, number>;
  fits: Record<string, { params: Record<string, number>; r2?: number; n?: number }>;
  heldout_r2: number;
  token_cost_per_tool: Record<string, number>;
}
export interface SampleRenders {
  tool: ToolIR;
  openai: unknown[];
  renders: { format_id: string; name: string; family: string; novel: boolean; two_stage: boolean; default_protocol: string; text: string; chars: number; tokens_estimate: number; instructions: string }[];
}

export interface EvidenceFiles {
  facts: Fact[];
  formats: Record<string, FormatEntry>;
  protocols: Record<string, ProtocolEntry>;
  core_main: { rows: CoreMainRow[] };
  families: { rows: FamilyRow[]; checkpoints?: CheckpointRow[] };
  protocol_crossing: Crossing;
  tool_count: ToolCount;
  tiers: Tiers;
  cost: Cost;
  injection: Injection;
  disclosure: Disclosure;
  selection: Selection;
  ladder: Ladder;
  zoo: Zoo;
  surface: Surface;
  sample_renders: SampleRenders;
}
export type EvidenceName = keyof EvidenceFiles;

/** Files the advisor needs; surface is optional (its source lives in the results repository). */
export const ADVISOR_FILES = ["facts", "formats", "core_main", "families", "protocol_crossing", "tool_count", "tiers", "cost", "injection", "disclosure", "selection", "zoo"] as const;

const BASE = (import.meta.env?.BASE_URL as string | undefined) ?? "/";
const cache = new Map<string, Promise<unknown>>();

export function evidenceUrl(name: string): string {
  return `${BASE}data/framework/${name}.json`;
}

export function loadEnvelope<N extends EvidenceName>(name: N): Promise<Envelope<EvidenceFiles[N]> | null> {
  if (!cache.has(name)) {
    cache.set(
      name,
      fetch(evidenceUrl(name))
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null),
    );
  }
  return cache.get(name) as Promise<Envelope<EvidenceFiles[N]> | null>;
}

export function loadManifest(): Promise<Manifest | null> {
  if (!cache.has("manifest")) {
    cache.set(
      "manifest",
      fetch(evidenceUrl("manifest"))
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null),
    );
  }
  return cache.get("manifest") as Promise<Manifest | null>;
}

export interface Loaded<T> {
  data: T | null;
  envelope: Envelope<T> | null;
  loading: boolean;
  missing: boolean;
}

export function useEvidence<N extends EvidenceName>(name: N): Loaded<EvidenceFiles[N]> {
  const [state, setState] = useState<Loaded<EvidenceFiles[N]>>({ data: null, envelope: null, loading: true, missing: false });
  useEffect(() => {
    let alive = true;
    loadEnvelope(name).then((env) => {
      if (alive) setState({ data: env ? env.data : null, envelope: env, loading: false, missing: !env });
    });
    return () => {
      alive = false;
    };
  }, [name]);
  return state;
}

export function useManifest(): Manifest | null {
  const [m, setM] = useState<Manifest | null>(null);
  useEffect(() => {
    let alive = true;
    loadManifest().then((x) => alive && setM(x));
    return () => {
      alive = false;
    };
  }, []);
  return m;
}

/** Load everything the advisor needs in one go. */
export async function loadAdvisorEvidence(): Promise<Evidence | null> {
  const names = [...ADVISOR_FILES, "surface"] as const;
  const envs = await Promise.all(names.map((n) => loadEnvelope(n as EvidenceName)));
  const manifest = await loadManifest();
  const out: Partial<EvidenceFiles> = {};
  for (const [i, n] of names.entries()) {
    const env = envs[i];
    if (!env && n !== "surface") return null;
    if (env) (out as Record<string, unknown>)[n] = env.data;
  }
  return { ...(out as Omit<EvidenceFiles, "surface" | "sample_renders">), surface: (out.surface as Surface | undefined) ?? null, version: manifest?.evidence_version ?? "unknown" };
}

export type Evidence = Omit<EvidenceFiles, "surface" | "sample_renders" | "protocols"> & {
  surface: Surface | null;
  version: string;
};

export function useAdvisorEvidence(): { evidence: Evidence | null; loading: boolean } {
  const [s, setS] = useState<{ evidence: Evidence | null; loading: boolean }>({ evidence: null, loading: true });
  useEffect(() => {
    let alive = true;
    loadAdvisorEvidence().then((e) => alive && setS({ evidence: e, loading: false }));
    return () => {
      alive = false;
    };
  }, []);
  return s;
}

export function factMap(facts: Fact[] | null | undefined): Record<string, Fact> {
  return Object.fromEntries((facts ?? []).map((f) => [f.id, f]));
}
