import { describe, expect, it } from "vitest";
import { countAccuracy, expit, logit, recommend, resolveModel, type Situation } from "../lib/advisor";
import { loadTools } from "../lib/tools";
import { diskEvidence } from "./evidenceLoader";
import { readEvidence } from "./fixtures";

const ev = diskEvidence();

describe("advisor on the shipped evidence", () => {
  if (!ev) {
    it.skip("evidence files are missing", () => {});
    return;
  }
  it("the Qwen 3 family at 8 tools and tier 3: XML with xml_call, 77.7 (65.30 to 77.70)", () => {
    const r = recommend(ev, { family: "qwen3", n_tools: 8, tier: 3 });
    expect(r.format_id).toBe("xml_schema");
    expect(r.protocol_id).toBe("xml_call");
    expect(r.expected_accuracy).toBeCloseTo(77.7, 2);
    expect(r.interval[0]).toBeCloseTo(65.3, 2);
    expect(r.interval[1]).toBeCloseTo(77.7, 2);
    expect(r.basis).toBe("family:qwen3");
    expect(r.basis_note).toBe("mean of 7 checkpoints, 0.6 to 32B");
    expect(r.catalogue.strategy).toBe("one_shot");
    expect(r.explanation).toContain("Qwen 3");
    expect(r.explanation).toContain("77.7%");
    expect(r.explanation).toContain("not itself evaluated");
    expect(r.warnings.some((w) => w.includes("12.5%"))).toBe(true);
    expect(r.schema_tokens).toBe(2836);
  });
  it("a checkpoint of the study uses its own row (review finding)", () => {
    const r = recommend(ev, { model: "Qwen/Qwen3-8B", n_tools: 8, tier: 3 });
    expect(r.basis).toBe("checkpoint:Qwen/Qwen3-8B");
    expect(r.resolution.matched_by).toBe("checkpoint");
    expect(r.expected_accuracy).toBeCloseTo(90.0, 2);
    expect(recommend(ev, { model: "Qwen/Qwen3-0.6B" }).expected_accuracy).toBeCloseTo(58.7, 2);
    expect(r.measure_hint).toContain("--no-thinking");
  });
  it("never ranks on clipped values: Qwen 3 at 2 tools, tier 2 keeps XML (review finding)", () => {
    const r = recommend(ev, { family: "qwen3", n_tools: 2, tier: 2 });
    expect(r.format_id).toBe("xml_schema");
    expect(r.warnings.some((w) => w.includes("clipped"))).toBe(false);
  });
  it("a tier gain is not carried to 300 tools (review finding)", () => {
    const r = recommend(ev, { model: "Qwen/Qwen3-8B", n_tools: 300, tier: 2 });
    expect(r.format_id).not.toBe("json_minimal");
    const min = recommend(ev, { family: "qwen3", candidates: ["json_minimal"], n_tools: 256, tier: 2 });
    const count = recommend(ev, { family: "qwen3", candidates: ["json_minimal"], n_tools: 256, tier: 3 });
    expect(min.expected_accuracy).toBeCloseTo(count.expected_accuracy, 6);
  });
  it("combines shifts in log-odds", () => {
    const r = recommend(ev, { family: "qwen3", candidates: ["xml_schema"], protocol: "json_object" });
    expect(r.expected_accuracy).toBeCloseTo(expit(logit(77.7) + logit(57.6) - logit(69.8)), 2);
  });
  it("refuses NaN and infinite sizes, and duplicate candidates count once", () => {
    expect(() => recommend(ev, { params_b: Number.NaN })).toThrow(/params_b/);
    expect(() => recommend(ev, { params_b: Number.POSITIVE_INFINITY })).toThrow(/params_b/);
    const dup = recommend(ev, { family: "qwen3", candidates: ["xml_schema", "xml_schema", "json_minimal"] });
    expect(dup.tied_with).not.toContain("xml_schema");
    expect(dup.alternatives.map((a) => a.format_id)).toEqual(["json_minimal"]);
  });
  it("resolves anchors, patterns and sizes", () => {
    expect(resolveModel(ev, "claude-opus-5-5").anchor).toBe("Claude Opus 5.5 (medium)");
    expect(resolveModel(ev, "claude-opus-5").anchor).toBe("Claude Opus 5 (medium)");
    expect(resolveModel(ev, "claude-opus-5-5-medium-run2").anchor).toBe("Claude Opus 5.5 (medium)");
    expect(resolveModel(ev, "Salesforce/Llama-xLAM-2-70b-fc-r").family).toBe("llama3-tool");
    expect(resolveModel(ev, "Salesforce/xLAM-2-1b-fc-r").family).toBe("xlam");
    const big = resolveModel(ev, "someorg/Qwen3.5-397B-A17B-custom");
    expect(big.family).toBe("qwen3.5-large");
    expect(big.params_b).toBe(397);
    expect(resolveModel(ev, "totally-unknown-model").matched_by).toBe("none");
    expect(resolveModel(ev, null, "gemma4").matched_by).toBe("family");
  });
  it("uses the pooled table under the symmetric rule and says so", () => {
    const r = recommend(ev, { model: "Qwen/Qwen3-8B", rule: "symmetric" });
    expect(r.basis).toBe("pooled");
    expect(r.warnings.join(" ")).toContain("family evidence exists only under the main rule");
  });
  it("interpolates the count curve in log2 and clamps past 256", () => {
    const [v8] = countAccuracy(ev, "xml_schema", 8);
    const [v16] = countAccuracy(ev, "xml_schema", 16);
    const [v11] = countAccuracy(ev, "xml_schema", 11);
    expect(v11).toBeLessThan(v8);
    expect(v11).toBeGreaterThan(v16);
    expect(countAccuracy(ev, "xml_schema", 400)).toEqual([27.8, true]);
    const r = recommend(ev, { n_tools: 400 });
    expect(r.warnings.join(" ")).toContain("more than 256 tools");
  });
  it("picks the catalogue strategy by tool count", () => {
    expect(recommend(ev, { n_tools: 16 }).catalogue.strategy).toBe("one_shot");
    expect(recommend(ev, { n_tools: 40 }).catalogue.strategy).toBe("retrieve");
    expect(recommend(ev, { n_tools: 64 }).catalogue.strategy).toBe("two_stage");
    expect(recommend(ev, { n_tools: 8, context_tokens: 400 }).catalogue.strategy).toBe("two_stage");
    const fits = recommend(ev, { n_tools: 8, context_tokens: 4000 });
    expect(fits.catalogue.strategy).toBe("one_shot");
    expect(fits.schema_tokens! <= 2000).toBe(true);
  });
  it("breaks the disclosure tie at 8 tools toward 16, as the package does (review finding)", () => {
    const r = recommend(ev, { family: "qwen3", n_tools: 8, tier: 3 });
    expect(r.catalogue.reason).toContain("at 16 tools");
    expect(r.catalogue.reason).toContain("interval that includes zero");
  });
  it("filters by token budget and falls back to the minimal schema", () => {
    const r = recommend(ev, { n_tools: 8, token_budget: 1000 });
    expect(r.format_id).toBe("json_minimal");
    const none = recommend(ev, { n_tools: 64, token_budget: 100 });
    expect(none.format_id).toBe("json_minimal");
    expect(none.catalogue.strategy).toBe("two_stage");
    expect(none.warnings.join(" ")).toContain("no core format fits the budget");
  });
  it("ranks by accuracy per cost under the cost objective", () => {
    const r = recommend(ev, { objective: "cost", n_tools: 8 });
    expect(r.cost_per_request).not.toBeNull();
    expect(r.alternatives.every((a) => a.score <= (r.expected_accuracy / (r.cost_per_request ?? 1)) + 1e-6)).toBe(true);
  });
  it("switches protocol only on a gain of 2.0 or more, and honours a fixed protocol", () => {
    const r = recommend(ev, { protocol: "json_object", family: "qwen3" });
    expect(r.protocol_id).toBe("json_object");
    const free = recommend(ev, { rule: "symmetric" });
    expect(["json_object", "xml_call", "python_call", "nl_intent", "tool_call_tags"]).toContain(free.protocol_id);
  });
  it("gives guard advice for third-party tools", () => {
    const r = recommend(ev, { family: "qwen3", third_party_tools: true });
    expect(r.guard?.action).toBe("strip");
    const m = recommend(ev, { candidates: ["json_minimal"], third_party_tools: true });
    expect(m.guard?.action).toBe("none");
  });
  it("takes tool count and tier from pasted tools and renders their tokens", () => {
    const tools = loadTools([{ type: "function", function: { name: "f", description: "d", parameters: { type: "object", properties: { a: { type: "string" } }, required: ["a"] } } }]).tools;
    const r = recommend(ev, { family: "qwen3" }, tools);
    expect(r.situation.n_tools).toBe(1);
    expect(r.situation.tier).toBe(1);
    expect(r.tokens_source).toBe("rendered");
  });
  it("refuses two-stage ids as candidates", () => {
    expect(() => recommend(ev, { candidates: ["names_then_schema"] })).toThrow(/two-stage/);
  });
});

interface AdvisorCases {
  data: { cases: { situation: Partial<Situation>; expected: { format_id: string; protocol_id: string; expected_accuracy: number; interval: [number, number]; basis: string; catalogue_strategy: string; tied_with: string[]; catalogue_reason: string; schema_tokens: number | null; cost_per_request: number | null } }[] };
}
const parity = readEvidence<AdvisorCases>("advisor_cases");

describe("parity with toolform.advisor (advisor_cases.json)", () => {
  if (!parity || !ev) {
    it.skip("advisor_cases.json is missing: it is written by the package's data build; run npm run sync once it exists", () => {});
    return;
  }
  for (const [i, c] of parity.data.cases.entries()) {
    it(`case ${i}: ${JSON.stringify(c.situation).slice(0, 80)}`, () => {
      const r = recommend(ev, c.situation);
      expect(r.format_id).toBe(c.expected.format_id);
      expect(r.protocol_id).toBe(c.expected.protocol_id);
      expect(r.basis).toBe(c.expected.basis);
      expect(r.catalogue.strategy).toBe(c.expected.catalogue_strategy);
      expect(Math.abs(r.expected_accuracy - c.expected.expected_accuracy)).toBeLessThanOrEqual(0.01);
      expect(Math.abs(r.interval[0] - c.expected.interval[0])).toBeLessThanOrEqual(0.01);
      expect(Math.abs(r.interval[1] - c.expected.interval[1])).toBeLessThanOrEqual(0.01);
      expect(r.tied_with).toEqual(c.expected.tied_with);
      expect(r.catalogue.reason).toBe(c.expected.catalogue_reason);
      expect(r.schema_tokens).toBe(c.expected.schema_tokens);
      if (c.expected.cost_per_request === null) expect(r.cost_per_request).toBeNull();
      else expect(Math.abs((r.cost_per_request ?? 0) - c.expected.cost_per_request)).toBeLessThanOrEqual(1e-8);
    });
  }
});
