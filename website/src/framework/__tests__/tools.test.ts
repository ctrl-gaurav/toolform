import { describe, expect, it } from "vitest";
import { detectKind, loadTools, LoaderError, tierEstimate, type ToolIR, type TypeIR, type ParamIR } from "../lib/tools";
import { readEvidence } from "./fixtures";

interface RenderCases {
  data: { cases: { id: string; openai: unknown[]; ir: { tools: ToolIR[] } }[] };
}

/* Only what JSON Schema can carry: the IR also holds kernels, domains and tags,
 * which an OpenAI tool file never has. */
function shapeType(t: TypeIR | null | undefined): unknown {
  if (!t) return null;
  const c = Object.fromEntries(Object.entries(t.constraints ?? {}).filter(([, v]) => v !== null && v !== undefined));
  return {
    kind: t.kind,
    item: shapeType(t.item),
    fields: (t.fields ?? []).map(shapeParam),
    enum_values: t.enum_values ?? [],
    union_of: (t.union_of ?? []).map(shapeType),
    constraints: c,
  };
}
function shapeParam(p: ParamIR): unknown {
  return { name: p.name, required: p.required, description: p.description ?? "", default: p.default ?? null, type: shapeType(p.type) };
}
function shape(t: ToolIR): unknown {
  return { name: t.name, description: t.description, params: t.params.map(shapeParam) };
}

const cases = readEvidence<RenderCases>("render_cases");

describe("OpenAI JSON to the IR", () => {
  if (!cases) {
    it.skip("render_cases.json is missing", () => {});
    return;
  }
  for (const c of cases.data.cases) {
    it(`${c.id}: the loader reproduces the case's IR`, () => {
      const loaded = loadTools(c.openai);
      expect(loaded.kind).toBe("openai");
      expect(loaded.tools.map(shape)).toEqual(c.ir.tools.map(shape));
    });
  }
});

describe("loaders", () => {
  const fn = { name: "f", description: "d", parameters: { type: "object", properties: { x: { type: "string" } }, required: ["x"] } };
  it("detects every accepted shape", () => {
    expect(detectKind([{ type: "function", function: fn }])).toBe("openai");
    expect(detectKind({ tools: [fn] })).toBe("openai");
    expect(detectKind([{ name: "f", input_schema: fn.parameters }])).toBe("anthropic");
    expect(detectKind({ tools: [{ name: "f", inputSchema: fn.parameters }] })).toBe("mcp");
    expect(detectKind({ jsonrpc: "2.0", id: 1, result: { tools: [{ name: "f", inputSchema: {} }] } })).toBe("mcp");
    expect(detectKind({ tools: [{ name: "f", params: [{ name: "x", type: { kind: "string" }, required: true }] }] })).toBe("ir");
  });
  it("resolves $ref, anyOf with null, const and constraints", () => {
    const t = loadTools([
      {
        type: "function",
        function: {
          name: "g",
          parameters: {
            type: "object",
            $defs: { Unit: { type: "string", enum: ["kg", "lb"] } },
            properties: {
              unit: { $ref: "#/$defs/Unit" },
              n: { anyOf: [{ type: "integer", minimum: 1 }, { type: "null" }] },
              k: { const: "fixed" },
              s: { type: ["string", "null"], maxLength: 4 },
            },
          },
        },
      },
    ]).tools[0];
    expect(t.params[0].type).toEqual({ kind: "enum", enum_values: ["kg", "lb"], base: "string" });
    expect(t.params[1].type).toEqual({ kind: "integer", constraints: { minimum: 1 } });
    expect(t.params[2].type.enum_values).toEqual(["fixed"]);
    expect(t.params[3].type).toEqual({ kind: "string", constraints: { max_length: 4 } });
  });
  it("rejects duplicates and bad JSON with a clear message", () => {
    expect(() => loadTools([fn, fn])).toThrow(/duplicate tool name "f"/);
    expect(() => loadTools("{not json")).toThrow(LoaderError);
    expect(() => loadTools([{ hello: 1 }])).toThrow(/could not tell/);
  });
  it("estimates the tier from nesting and unions", () => {
    const flat = loadTools([fn]).tools;
    expect(tierEstimate(flat)).toBe(1);
    const nested = loadTools([{ name: "h", parameters: { type: "object", properties: { o: { type: "object", properties: { a: { type: "string" } } } } } }]).tools;
    expect(tierEstimate(nested)).toBe(3);
  });
});
