/* The canonical tool IR in the browser, and the loaders that produce it.
 *
 * The shapes are exactly what toolform.ir's to_dict() writes, so an IR file
 * from the Python SDK loads here unchanged and the renderers see the same
 * tree. The JSON Schema converter follows toolform.sdk.jsonschema: $ref
 * resolution, anyOf and oneOf, enums, const, nested objects and constraints.
 */

export type Kind =
  | "string" | "integer" | "number" | "boolean" | "array"
  | "object" | "enum" | "union" | "null" | "any";

export interface Constraints {
  minimum?: number | null;
  maximum?: number | null;
  min_length?: number | null;
  max_length?: number | null;
  min_items?: number | null;
  max_items?: number | null;
  pattern?: string | null;
  format?: string | null;
}

export interface TypeIR {
  kind: Kind;
  item?: TypeIR | null;
  fields?: ParamIR[];
  enum_values?: unknown[];
  union_of?: TypeIR[];
  base?: Kind | null;
  constraints?: Constraints;
}

export interface ParamIR {
  name: string;
  type: TypeIR;
  required: boolean;
  description?: string;
  default?: unknown;
  example?: unknown;
}

export interface ToolIR {
  name: string;
  description: string;
  params: ParamIR[];
  domain?: string;
  category?: string;
  origin?: string;
  returns?: TypeIR | null;
  returns_description?: string;
  examples?: Record<string, unknown>[];
  tags?: string[];
  kernel?: string | null;
  kernel_args?: Record<string, unknown>;
  annotations?: Record<string, unknown>;
}

export type SourceKind = "openai" | "anthropic" | "mcp" | "ir";

export interface LoadedTools {
  tools: ToolIR[];
  kind: SourceKind;
}

export class LoaderError extends Error {}

/* ------------------------------------------------------------------ helpers */

/** Python's `x is not None`, for values read from JSON. */
export function isSet(v: unknown): boolean {
  return v !== undefined && v !== null;
}

type Json = Record<string, unknown>;

function isObj(v: unknown): v is Json {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

const SCALARS: Record<string, Kind> = {
  string: "string", integer: "integer", number: "number", boolean: "boolean", null: "null",
};

function constraintsFrom(spec: Json): Constraints | undefined {
  const c: Constraints = {};
  const num = (k: string) => (typeof spec[k] === "number" ? (spec[k] as number) : undefined);
  const min = num("minimum") ?? num("exclusiveMinimum");
  const max = num("maximum") ?? num("exclusiveMaximum");
  if (min !== undefined) c.minimum = min;
  if (max !== undefined) c.maximum = max;
  if (num("minLength") !== undefined) c.min_length = num("minLength");
  if (num("maxLength") !== undefined) c.max_length = num("maxLength");
  if (num("minItems") !== undefined) c.min_items = num("minItems");
  if (num("maxItems") !== undefined) c.max_items = num("maxItems");
  if (typeof spec.pattern === "string" && spec.pattern) c.pattern = spec.pattern;
  if (typeof spec.format === "string" && spec.format) c.format = spec.format;
  return Object.keys(c).length ? c : undefined;
}

function withConstraints(t: TypeIR, spec: Json): TypeIR {
  const c = constraintsFrom(spec);
  return c ? { ...t, constraints: c } : t;
}

function resolveRef(ref: string, defs: Json | undefined): Json | undefined {
  const m = ref.match(/^#\/(?:\$defs|definitions)\/(.+)$/);
  if (!m || !defs) return undefined;
  const hit = defs[m[1]];
  return isObj(hit) ? hit : undefined;
}

function isNullSpec(s: unknown): boolean {
  return isObj(s) && s.type === "null";
}

/** One JSON Schema fragment to a TypeIR. */
export function typeFromJsonSchema(spec: unknown, defs?: Json, depth = 0): TypeIR {
  if (!isObj(spec) || depth > 12) return { kind: "any" };
  if (typeof spec.$ref === "string") {
    const target = resolveRef(spec.$ref, defs);
    return target ? typeFromJsonSchema(target, defs, depth + 1) : { kind: "any" };
  }
  const branches = (spec.anyOf ?? spec.oneOf) as unknown;
  if (Array.isArray(branches)) {
    const real = branches.filter((b) => !isNullSpec(b));
    if (real.length === 1) return typeFromJsonSchema(real[0], defs, depth + 1);
    if (real.length === 0) return { kind: "null" };
    return { kind: "union", union_of: real.map((b) => typeFromJsonSchema(b, defs, depth + 1)) };
  }
  let type = spec.type as unknown;
  if (Array.isArray(type)) {
    const real = type.filter((x) => x !== "null");
    if (real.length > 1) {
      return {
        kind: "union",
        union_of: real.map((x) => typeFromJsonSchema({ ...spec, type: x }, defs, depth + 1)),
      };
    }
    type = real[0];
  }
  if (Array.isArray(spec.enum)) {
    const base: Kind = type === "number" || type === "integer" || type === "boolean" ? (type as Kind) : "string";
    return withConstraints({ kind: "enum", enum_values: [...spec.enum], base }, spec);
  }
  if ("const" in spec) {
    const base: Kind = typeof spec.const === "number" ? (Number.isInteger(spec.const) ? "integer" : "number") : "string";
    return { kind: "enum", enum_values: [spec.const], base };
  }
  if (type === "array") {
    const t: TypeIR = { kind: "array" };
    if (isObj(spec.items)) t.item = typeFromJsonSchema(spec.items, defs, depth + 1);
    return withConstraints(t, spec);
  }
  if (type === "object" || isObj(spec.properties)) {
    return withConstraints({ kind: "object", fields: paramsFromJsonSchema(spec, defs, depth + 1) }, spec);
  }
  if (typeof type === "string" && SCALARS[type]) return withConstraints({ kind: SCALARS[type] }, spec);
  return { kind: "any" };
}

/** The `properties` of an object schema, in order, as parameters. */
export function paramsFromJsonSchema(parameters: unknown, defs?: Json, depth = 0): ParamIR[] {
  if (!isObj(parameters)) return [];
  const localDefs = (isObj(parameters.$defs) ? parameters.$defs : isObj(parameters.definitions) ? parameters.definitions : undefined) as Json | undefined;
  const allDefs = localDefs ? { ...(defs ?? {}), ...localDefs } : defs;
  const props = isObj(parameters.properties) ? parameters.properties : {};
  const required = new Set(Array.isArray(parameters.required) ? (parameters.required as string[]) : []);
  return Object.entries(props).map(([name, raw]) => {
    const spec = isObj(raw) ? raw : {};
    const p: ParamIR = {
      name,
      type: typeFromJsonSchema(spec, allDefs, depth),
      required: required.has(name),
    };
    if (typeof spec.description === "string" && spec.description) p.description = spec.description;
    if (isSet(spec.default)) p.default = spec.default;
    if (Array.isArray(spec.examples) && spec.examples.length) p.example = spec.examples[0];
    return p;
  });
}

export function toolFromFunctionSchema(name: string, description: string, parameters: unknown, extra?: Json): ToolIR {
  if (!name || typeof name !== "string") throw new LoaderError("every tool needs a string name");
  const t: ToolIR = {
    name,
    description: description ?? "",
    params: paramsFromJsonSchema(parameters),
    domain: "user",
    category: "user",
    origin: "user",
  };
  const ret = extra?.returns ?? extra?.output_schema ?? extra?.outputSchema;
  if (isObj(ret)) {
    t.returns = typeFromJsonSchema(ret);
    if (typeof ret.description === "string") t.returns_description = ret.description;
  }
  return t;
}

/* ------------------------------------------------------------------ loaders */

function listOf(obj: unknown, key: string): unknown[] | null {
  if (Array.isArray(obj)) return obj;
  if (isObj(obj) && Array.isArray(obj[key])) return obj[key] as unknown[];
  return null;
}

export function detectKind(obj: unknown): SourceKind {
  if (isObj(obj) && ("jsonrpc" in obj || (isObj(obj.result) && Array.isArray((obj.result as Json).tools)))) return "mcp";
  const items = listOf(obj, "tools") ?? (isObj(obj) ? [obj] : null);
  if (!items || items.length === 0) throw new LoaderError("no tools found: expected a list of tools or an object with a \"tools\" list");
  const first = items.find(isObj);
  if (!first) throw new LoaderError("tools must be JSON objects");
  if ("inputSchema" in first) return "mcp";
  if ("input_schema" in first) return "anthropic";
  if (Array.isArray(first.params) && (first.params as unknown[]).every((p) => isObj(p) && isObj(p.type) && "kind" in (p.type as Json))) return "ir";
  if ("function" in first || "parameters" in first || (first.type === "function" && "name" in first)) return "openai";
  throw new LoaderError(
    "could not tell what shape this is. Accepted: OpenAI function tools, Anthropic tools (input_schema), an MCP tools/list result (inputSchema), or ToolForm IR.",
  );
}

function fromOpenAI(obj: unknown): ToolIR[] {
  const items = listOf(obj, "tools") ?? [obj];
  return items.map((raw) => {
    if (!isObj(raw)) throw new LoaderError("each OpenAI tool must be an object");
    const fn = isObj(raw.function) ? raw.function : raw;
    return toolFromFunctionSchema(fn.name as string, (fn.description as string) ?? "", fn.parameters, fn);
  });
}

function fromAnthropic(obj: unknown): ToolIR[] {
  const items = listOf(obj, "tools") ?? [obj];
  return items.map((raw) => {
    if (!isObj(raw)) throw new LoaderError("each Anthropic tool must be an object");
    return toolFromFunctionSchema(raw.name as string, (raw.description as string) ?? "", raw.input_schema);
  });
}

function fromMCP(obj: unknown): ToolIR[] {
  let root = obj;
  if (isObj(root) && isObj(root.result)) root = root.result;
  const items = listOf(root, "tools");
  if (!items) throw new LoaderError("an MCP tools/list result needs a \"tools\" list");
  return items.map((raw) => {
    if (!isObj(raw)) throw new LoaderError("each MCP tool must be an object");
    const t = toolFromFunctionSchema(raw.name as string, (raw.description as string) ?? "", raw.inputSchema, raw);
    const mcp: Json = {};
    if (isObj(raw.annotations)) mcp.annotations = raw.annotations;
    if (typeof raw.title === "string") mcp.title = raw.title;
    if (Object.keys(mcp).length) t.annotations = { mcp };
    return t;
  });
}

function fromIR(obj: unknown): ToolIR[] {
  const items = listOf(obj, "tools");
  if (!items) throw new LoaderError("an IR file is {\"tools\": [...]} or a list of tools");
  return items.map((raw) => {
    if (!isObj(raw) || typeof raw.name !== "string") throw new LoaderError("each IR tool needs a name");
    return {
      ...(raw as unknown as ToolIR),
      description: (raw.description as string) ?? "",
      params: (raw.params as ParamIR[]) ?? [],
    };
  });
}

/** Parse JSON text or take an object, detect its shape and load it. */
export function loadTools(input: unknown, kind: SourceKind | "auto" = "auto"): LoadedTools {
  let obj = input;
  if (typeof input === "string") {
    try {
      obj = JSON.parse(input);
    } catch (e) {
      throw new LoaderError(`not valid JSON: ${(e as Error).message}`);
    }
  }
  const k = kind === "auto" ? detectKind(obj) : kind;
  const tools = k === "openai" ? fromOpenAI(obj) : k === "anthropic" ? fromAnthropic(obj) : k === "mcp" ? fromMCP(obj) : fromIR(obj);
  const seen = new Set<string>();
  for (const t of tools) {
    if (seen.has(t.name)) throw new LoaderError(`duplicate tool name "${t.name}"`);
    seen.add(t.name);
  }
  return { tools, kind: k };
}

/* ------------------------------------------------------------------ analysis */

function depthOf(t: TypeIR): number {
  if (t.kind === "object" && t.fields?.length) return 1 + Math.max(0, ...t.fields.map((f) => depthOf(f.type)));
  if (t.kind === "array" && t.item) return depthOf(t.item);
  if (t.kind === "union" && t.union_of) return Math.max(0, ...t.union_of.map(depthOf));
  return 0;
}

function countUnions(t: TypeIR): number {
  let n = t.kind === "union" ? 1 : 0;
  if (t.fields) for (const f of t.fields) n += countUnions(f.type);
  if (t.item) n += countUnions(t.item);
  if (t.union_of) for (const u of t.union_of) n += countUnions(u);
  return n;
}

/**
 * The generator tier a tool set most resembles, 1 to 5; the hardest tool sets
 * the risk. The rule of Toolset.tier_estimate in the SDK.
 */
export function tierEstimate(tools: ToolIR[]): number {
  let tier = 1;
  for (const t of tools) {
    const depth = Math.max(0, ...t.params.map((p) => depthOf(p.type)));
    const unions = t.params.reduce((n, p) => n + countUnions(p.type), 0);
    let k = 1;
    if (depth >= 3 || unions >= 2) k = 5;
    else if (depth === 2 || unions === 1) k = 4;
    else if (depth === 1) k = 3;
    else if (t.params.some((p) => p.type.kind === "enum" || !p.required || (p.type.constraints && Object.values(p.type.constraints).some(isSet)))) k = 2;
    tier = Math.max(tier, k);
  }
  return tier;
}

/** Every parameter name at any depth, for the guard's schema checks. */
export function paramNames(tool: ToolIR): string[] {
  const out: string[] = [];
  const walk = (ps: ParamIR[]) => {
    for (const p of ps) {
      out.push(p.name);
      const visit = (t: TypeIR | null | undefined) => {
        if (!t) return;
        if (t.fields) walk(t.fields);
        visit(t.item);
        t.union_of?.forEach(visit);
      };
      visit(p.type);
    }
  };
  walk(tool.params);
  return out;
}
