/* Shared pieces of the renderer port.
 *
 * The eight core renderers of toolform.formats print values the way Python
 * prints them: str(False) is "False", json.dumps(1.5) is "1.5", repr of a
 * list uses single quotes. The helpers here reproduce those rules so the
 * browser writes the same bytes as the Python SDK. One gap cannot be closed:
 * JSON has no separate float type, so a value written as 1.0 in a tool file
 * reaches the browser as 1 and prints as "1" where Python prints "1.0".
 */

import type { ParamIR, ToolIR, TypeIR } from "../tools";
import { isSet } from "../tools";

export interface RenderOptions {
  descriptions: boolean;
  constraints: boolean;
  defaults: boolean;
  returns: boolean;
  minify: boolean;
  indent: number;
}

export const DEFAULT_OPTIONS: RenderOptions = {
  descriptions: true,
  constraints: true,
  defaults: true,
  returns: true,
  minify: false,
  indent: 2,
};

/* ------------------------------------------------------------------ numbers */

/** repr() of a Python float, for values that are not whole numbers. */
function pyFloatRepr(x: number): string {
  if (Number.isNaN(x)) return "nan";
  if (!Number.isFinite(x)) return x > 0 ? "inf" : "-inf";
  const ax = Math.abs(x);
  if (ax !== 0 && (ax < 1e-4 || ax >= 1e16)) {
    // Python: 1e-05, 1.5e+16. JavaScript: 1e-5, 1.5e+16.
    const [mant, exp] = x.toExponential().split("e");
    const e = parseInt(exp, 10);
    const sign = e < 0 ? "-" : "+";
    const digits = String(Math.abs(e)).padStart(2, "0");
    return `${mant}e${sign}${digits}`;
  }
  return String(x);
}

/** A JSON number printed as Python prints the int or float it loads as. */
export function pyNumber(x: number): string {
  if (Number.isInteger(x) && Math.abs(x) < 1e16) return String(x);
  return pyFloatRepr(x);
}

/* ------------------------------------------------------------------ strings */

function pyReprString(s: string): string {
  const quote = s.includes("'") && !s.includes('"') ? '"' : "'";
  let out = quote;
  for (const ch of s) {
    const code = ch.codePointAt(0)!;
    if (ch === "\\") out += "\\\\";
    else if (ch === quote) out += "\\" + ch;
    else if (ch === "\n") out += "\\n";
    else if (ch === "\r") out += "\\r";
    else if (ch === "\t") out += "\\t";
    else if (code < 0x20 || code === 0x7f) out += "\\x" + code.toString(16).padStart(2, "0");
    else out += ch;
  }
  return out + quote;
}

/** Python repr() of a JSON value. */
export function pyRepr(v: unknown): string {
  if (v === null || v === undefined) return "None";
  if (typeof v === "boolean") return v ? "True" : "False";
  if (typeof v === "number") return pyNumber(v);
  if (typeof v === "string") return pyReprString(v);
  if (Array.isArray(v)) return "[" + v.map(pyRepr).join(", ") + "]";
  if (typeof v === "object") {
    return "{" + Object.entries(v as Record<string, unknown>).map(([k, x]) => `${pyReprString(k)}: ${pyRepr(x)}`).join(", ") + "}";
  }
  return String(v);
}

/** Python str() of a JSON value. */
export function pyStr(v: unknown): string {
  if (typeof v === "string") return v;
  return pyRepr(v);
}

/* ------------------------------------------------------------------ json.dumps */

export interface PyJsonOptions {
  indent?: number | null;
  itemSep?: string;
  keySep?: string;
  ensureAscii?: boolean;
}

function pyJsonString(s: string, ascii: boolean): string {
  let out = '"';
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    const c = s.charCodeAt(i);
    if (ch === '"') out += '\\"';
    else if (ch === "\\") out += "\\\\";
    else if (ch === "\n") out += "\\n";
    else if (ch === "\r") out += "\\r";
    else if (ch === "\t") out += "\\t";
    else if (ch === "\b") out += "\\b";
    else if (ch === "\f") out += "\\f";
    else if (c < 0x20 || (ascii && c > 0x7e)) out += "\\u" + c.toString(16).padStart(4, "0");
    else out += ch;
  }
  return out + '"';
}

/** json.dumps with Python's defaults (ensure_ascii on unless turned off). */
export function pyJson(v: unknown, opts: PyJsonOptions = {}, level = 0): string {
  const indent = opts.indent ?? null;
  const ascii = opts.ensureAscii ?? true;
  const itemSep = opts.itemSep ?? (indent !== null ? "," : ", ");
  const keySep = opts.keySep ?? ": ";
  if (v === null || v === undefined) return "null";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "number") {
    if (Number.isNaN(v)) return "NaN";
    if (!Number.isFinite(v)) return v > 0 ? "Infinity" : "-Infinity";
    return pyNumber(v);
  }
  if (typeof v === "string") return pyJsonString(v, ascii);
  const nl = indent !== null ? "\n" + " ".repeat(indent * (level + 1)) : "";
  const close = indent !== null ? "\n" + " ".repeat(indent * level) : "";
  if (Array.isArray(v)) {
    if (v.length === 0) return "[]";
    return "[" + nl + v.map((x) => pyJson(x, opts, level + 1)).join(itemSep + nl) + close + "]";
  }
  const entries = Object.entries(v as Record<string, unknown>);
  if (entries.length === 0) return "{}";
  return "{" + nl + entries.map(([k, x]) => pyJsonString(k, ascii) + keySep + pyJson(x, opts, level + 1)).join(itemSep + nl) + close + "}";
}

/** py_value in toolform.formats.common: a Python literal for a default. */
export function pyValue(v: unknown): string {
  if (v === null || v === undefined) return "None";
  if (typeof v === "boolean") return v ? "True" : "False";
  if (typeof v === "string") return `"${v}"`;
  if (Array.isArray(v) || typeof v === "object") return pyJson(v);
  return pyNumber(v as number);
}

/** js_value in toolform.formats.common. */
export function jsValue(v: unknown): string {
  if (v === null || v === undefined) return "null";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "string") return `"${v}"`;
  if (Array.isArray(v) || typeof v === "object") return pyJson(v);
  return pyNumber(v as number);
}

/** xml.sax.saxutils.escape */
export function xmlEscape(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/>/g, "&gt;").replace(/</g, "&lt;");
}

/* ------------------------------------------------------------------ options */

function stripTypeDesc(t: TypeIR): TypeIR {
  return {
    ...t,
    item: t.item ? stripTypeDesc(t.item) : t.item,
    fields: t.fields?.map(stripParamDesc),
    union_of: t.union_of?.map(stripTypeDesc),
  };
}
function stripParamDesc(p: ParamIR): ParamIR {
  return { ...p, description: "", example: undefined, type: stripTypeDesc(p.type) };
}
function stripTypeConstraints(t: TypeIR): TypeIR {
  return {
    ...t,
    constraints: undefined,
    item: t.item ? stripTypeConstraints(t.item) : t.item,
    fields: t.fields?.map((f) => ({ ...f, type: stripTypeConstraints(f.type) })),
    union_of: t.union_of?.map(stripTypeConstraints),
  };
}
function stripParamDefaults(p: ParamIR): ParamIR {
  const t = p.type.fields?.length ? { ...p.type, fields: p.type.fields.map(stripParamDefaults) } : p.type;
  return { ...p, default: undefined, example: undefined, type: t };
}

/** RenderOptions.apply_to: pre-strip the IR once so each renderer only lays out. */
export function applyOptions(tool: ToolIR, o: RenderOptions): ToolIR {
  let t: ToolIR = { ...tool };
  if (!o.descriptions) t = { ...t, description: "", returns_description: "", params: t.params.map(stripParamDesc), examples: [] };
  if (!o.constraints) t = { ...t, params: t.params.map((p) => ({ ...p, type: stripTypeConstraints(p.type) })) };
  if (!o.returns) t = { ...t, returns: null, returns_description: "" };
  if (!o.defaults) t = { ...t, params: t.params.map(stripParamDefaults) };
  return t;
}

/* ------------------------------------------------------------------ JSON Schema out */

type Obj = Record<string, unknown>;

function addConstraints(out: Obj, t: TypeIR): void {
  const c = t.constraints ?? {};
  if (isSet(c.minimum)) out.minimum = c.minimum;
  if (isSet(c.maximum)) out.maximum = c.maximum;
  if (isSet(c.min_length)) out.minLength = c.min_length;
  if (isSet(c.max_length)) out.maxLength = c.max_length;
  if (isSet(c.min_items)) out.minItems = c.min_items;
  if (isSet(c.max_items)) out.maxItems = c.max_items;
  if (c.pattern) out.pattern = c.pattern;
  if (c.format) out.format = c.format;
}

export function typeToJsonSchema(t: TypeIR, descriptions = true): Obj {
  let out: Obj;
  switch (t.kind) {
    case "enum":
      out = { type: t.base ?? "string", enum: [...(t.enum_values ?? [])] };
      break;
    case "union":
      out = { anyOf: (t.union_of ?? []).map((u) => typeToJsonSchema(u, descriptions)) };
      break;
    case "array":
      out = { type: "array" };
      if (t.item) out.items = typeToJsonSchema(t.item, descriptions);
      break;
    case "object": {
      const props: Obj = {};
      const required: string[] = [];
      for (const f of t.fields ?? []) {
        props[f.name] = paramToJsonSchema(f, descriptions);
        if (f.required) required.push(f.name);
      }
      out = { type: "object", properties: props };
      if (required.length) out.required = required;
      break;
    }
    case "any":
      out = {};
      break;
    case "null":
      out = { type: "null" };
      break;
    default:
      out = { type: t.kind };
  }
  addConstraints(out, t);
  return out;
}

export function paramToJsonSchema(p: ParamIR, descriptions = true): Obj {
  const out = typeToJsonSchema(p.type, descriptions);
  if (descriptions && p.description) out.description = p.description;
  if (isSet(p.default)) out.default = p.default;
  return out;
}

export type SchemaStyle = "openai" | "openai_flat" | "anthropic";

/** tool_to_json_schema in toolform.formats.common. */
export function toolToJsonSchema(tool: ToolIR, style: SchemaStyle = "openai", descriptions = true, includeReturns = true): Obj {
  const props: Obj = {};
  const required: string[] = [];
  for (const p of tool.params) {
    props[p.name] = paramToJsonSchema(p, descriptions);
    if (p.required) required.push(p.name);
  }
  const params: Obj = { type: "object", properties: props };
  if (required.length) params.required = required;
  const body: Obj = { name: tool.name };
  if (descriptions && tool.description) body.description = tool.description;
  if (style === "anthropic") body.input_schema = params;
  else body.parameters = params;
  if (includeReturns && tool.returns) {
    const rs = typeToJsonSchema(tool.returns, descriptions);
    if (descriptions && tool.returns_description) rs.description = tool.returns_description;
    body.returns = rs;
  }
  return style === "openai" ? { type: "function", function: body } : body;
}

/* ------------------------------------------------------------------ names and order */

export function pascal(s: string): string {
  return s
    .replace(/-/g, "_")
    .split("_")
    .filter(Boolean)
    .map((part) => part.slice(0, 1).toUpperCase() + part.slice(1))
    .join("");
}

/** Required parameters first, then optional, order kept within each. */
export function orderedParams(tool: ToolIR): ParamIR[] {
  return [...tool.params.filter((p) => p.required), ...tool.params.filter((p) => !p.required)];
}

export function objectTypeName(tool: ToolIR, p: ParamIR): string {
  return pascal(tool.name) + pascal(p.name);
}

/** collect_object_types: every nested object with a generated type name. */
export function collectObjectTypes(tool: ToolIR): [string, TypeIR][] {
  const found: [string, TypeIR][] = [];
  const seen = new Set<TypeIR>();
  const visit = (t: TypeIR, path: string) => {
    if (seen.has(t)) return;
    seen.add(t);
    if (t.kind === "object" && t.fields?.length) {
      found.push([path, t]);
      for (const f of t.fields) visit(f.type, path + pascal(f.name));
    } else if (t.kind === "array" && t.item) {
      visit(t.item, path + "Item");
    } else if (t.kind === "union") {
      (t.union_of ?? []).forEach((u, i) => visit(u, `${path}Alt${i + 1}`));
    }
  };
  for (const p of tool.params) visit(p.type, pascal(tool.name) + pascal(p.name));
  return found;
}

/** Python's str.isidentifier for the ASCII and Unicode letter cases we meet. */
export function isIdentifier(s: string): boolean {
  return /^[\p{L}_][\p{L}\p{N}_]*$/u.test(s);
}

export function requiredParams(t: ToolIR): ParamIR[] {
  return t.params.filter((p) => p.required);
}
export function optionalParams(t: ToolIR): ParamIR[] {
  return t.params.filter((p) => !p.required);
}

/** str.rstrip(".") */
export function rstripDots(s: string): string {
  return s.replace(/\.+$/, "");
}
