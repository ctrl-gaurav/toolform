import { describe, expect, it } from "vitest";
import { readEvidence } from "./fixtures";

/* Every evidence file the site reads, with the common envelope. */
const SITE_FILES = [
  "facts", "formats", "protocols", "core_main", "families", "protocol_crossing", "tool_count",
  "tiers", "cost", "injection", "disclosure", "selection", "ladder", "zoo", "sample_renders",
];

interface Env { schema_version: number; name: string; source: string[]; description: string; data: unknown }
interface Fact { id: string; value: number }

describe("evidence files in public/data/framework", () => {
  it("has a manifest listing every file", () => {
    const m = readEvidence<{ evidence_version: string; files: { name: string }[] }>("manifest");
    expect(m, "manifest.json is missing: run npm run sync").toBeTruthy();
    const names = new Set(m!.files.map((f) => f.name));
    for (const n of SITE_FILES) expect(names.has(n), `${n} not in the manifest`).toBe(true);
  });
  for (const n of SITE_FILES) {
    it(`${n}.json has the envelope`, () => {
      const env = readEvidence<Env>(n);
      expect(env, `${n}.json is missing`).toBeTruthy();
      expect(env!.schema_version).toBe(1);
      expect(env!.name).toBe(n);
      expect(Array.isArray(env!.source)).toBe(true);
      expect(env!.data).toBeTruthy();
    });
  }
  it("the headline facts equal the paper's numbers", () => {
    const facts = Object.fromEntries(readEvidence<{ data: Fact[] }>("facts")!.data.map((f) => [f.id, f.value]));
    const want: Record<string, number> = {
      n_formats: 129, n_protocols: 31, n_rules: 3, n_open_models: 100, n_proprietary_models: 12, n_domains: 24,
      n_real_tools: 66, n_real_requests: 1248, n_public_benchmarks: 6, schema_over_names: 57.09,
      xml_minus_json_main: 13.8, xml_minus_json_symmetric: 1.07, xml_minus_json_as_written: -3.28,
      protocol_ratio_main: 2.0, protocol_ratio_as_written: 1.22, grammar_hallucinated_free: 1.07,
      grammar_hallucinated_fixed: 0.01, injection_min: 38.48, injection_max: 54.16, tool_count_cost: 41.01,
      measure_eight: 69.18, fitted_rule: 64.35, always_json: 57.97,
    };
    for (const [k, v] of Object.entries(want)) expect(facts[k], k).toBe(v);
  });
  it("formats.json has 133 entries, 129 in the study", () => {
    const f = readEvidence<{ data: Record<string, { in_study: boolean }> }>("formats")!.data;
    expect(Object.keys(f).length).toBe(133);
    expect(Object.values(f).filter((x) => x.in_study).length).toBe(129);
  });
});
