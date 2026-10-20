import { describe, expect, it } from "vitest";
import { CORE_FORMATS, DEFAULT_PROTOCOL, protocolInstructions, renderFormat } from "../lib/render";
import { safeDump } from "../lib/render/yaml";
import { pyJson, pyRepr } from "../lib/render/common";
import { estimateTokens } from "../lib/tokens";
import type { ToolIR } from "../lib/tools";
import { readEvidence, trimLines } from "./fixtures";

interface RenderCases {
  data: { cases: { id: string; ir: { tools: ToolIR[] }; renders: Record<string, { text: string; instructions: string }> }[] };
}
interface SampleRenders {
  data: { tool: ToolIR; renders: { format_id: string; text: string; tokens_estimate: number }[] };
}

const cases = readEvidence<RenderCases>("render_cases");
const sample = readEvidence<SampleRenders>("sample_renders");

describe("render parity with toolform.formats", () => {
  if (!cases) {
    it.skip("render_cases.json is missing: run npm run sync (or the bootstrap) first", () => {});
    return;
  }
  for (const c of cases.data.cases) {
    for (const fid of CORE_FORMATS) {
      it(`${c.id} / ${fid}`, () => {
        const want = c.renders[fid];
        expect(want, `case ${c.id} has no ${fid} render`).toBeTruthy();
        expect(trimLines(renderFormat(c.ir.tools, fid))).toBe(trimLines(want.text));
        expect(protocolInstructions(DEFAULT_PROTOCOL[fid])).toBe(want.instructions);
      });
    }
  }
});

describe("the sample tool", () => {
  if (!sample) {
    it.skip("sample_renders.json is missing", () => {});
    return;
  }
  it("renders like the Python SDK in every core format, with the same token estimate", () => {
    for (const fid of CORE_FORMATS) {
      const row = sample.data.renders.find((r) => r.format_id === fid)!;
      const text = renderFormat([sample.data.tool], fid);
      expect(trimLines(text)).toBe(trimLines(row.text));
      expect(estimateTokens(text)).toBe(row.tokens_estimate);
    }
  });
});

describe("Python printing rules", () => {
  it("json.dumps defaults: ascii escapes and spaced separators", () => {
    expect(pyJson({ a: [1, "é"], b: null })).toBe('{"a": [1, "\\u00e9"], "b": null}');
    expect(pyJson([], { indent: 2 })).toBe("[]");
    expect(pyJson(1e-5)).toBe("1e-05");
  });
  it("repr of containers", () => {
    expect(pyRepr(["a", "it's", true, null])).toBe(`['a', "it's", True, None]`);
    expect(pyRepr({ k: 1.5 })).toBe("{'k': 1.5}");
  });
  it("PyYAML quoting", () => {
    expect(safeDump([{ a: "yes", b: "", c: "x: y", d: "- item", e: "plain text", f: "tab\there" }])).toBe(
      "- a: 'yes'\n  b: ''\n  c: 'x: y'\n  d: '- item'\n  e: plain text\n  f: \"tab\\there\"",
    );
    expect(safeDump([{ p: {}, q: [] }])).toBe("- p: {}\n  q: []");
  });
});
