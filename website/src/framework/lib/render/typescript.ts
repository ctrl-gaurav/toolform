/* typescript: port of TypeScriptSignatures in toolform/formats/typescript.py. */

import type { ParamIR, ToolIR, TypeIR } from "../tools";
import { isSet } from "../tools";
import { collectObjectTypes, isIdentifier, jsValue, objectTypeName, orderedParams, type RenderOptions } from "./common";

function tsScalar(t: TypeIR): string {
  switch (t.kind) {
    case "string":
      return "string";
    case "integer":
    case "number":
      return "number";
    case "boolean":
      return "boolean";
    case "object":
      return "Record<string, unknown>";
    case "array":
      return "unknown[]";
    case "null":
      return "null";
    default:
      return "unknown";
  }
}

export function tsType(t: TypeIR, tool?: ToolIR, p?: ParamIR): string {
  if (t.kind === "object" && t.fields?.length) {
    if (tool && p) return objectTypeName(tool, p);
    return "{ " + t.fields.map((f) => `${f.name}${f.required ? "" : "?"}: ${tsType(f.type)}`).join("; ") + " }";
  }
  if (t.kind === "array" && t.item) {
    const inner = tsType(t.item, tool, p);
    return isIdentifier(inner) || inner.endsWith("]") ? `${inner}[]` : `(${inner})[]`;
  }
  if (t.kind === "enum") return (t.enum_values ?? []).map(jsValue).join(" | ");
  if (t.kind === "union") return (t.union_of ?? []).map((u) => tsType(u, tool, p)).join(" | ");
  return tsScalar(t);
}

function tsParam(t: ToolIR, p: ParamIR, o: RenderOptions): string {
  let q = p.required ? "" : "?";
  let def = "";
  if (o.defaults && !p.required && isSet(p.default)) {
    q = "";
    def = ` = ${jsValue(p.default)}`;
  }
  return `${p.name}${q}: ${tsType(p.type, t, p)}${def}`;
}

export function renderTypeScript(tools: ToolIR[], o: RenderOptions): string {
  const out: string[] = [];
  for (const t of tools) {
    for (const [name, obj] of collectObjectTypes(t)) {
      out.push(`interface ${name} {`);
      for (const f of obj.fields ?? []) {
        if (o.descriptions && f.description) out.push(`  /** ${f.description} */`);
        out.push(`  ${f.name}${f.required ? "" : "?"}: ${tsType(f.type)};`);
      }
      out.push("}");
      out.push("");
    }
    if (o.descriptions && (t.description || t.params.some((p) => p.description))) {
      out.push("/**");
      if (t.description) out.push(` * ${t.description}`);
      for (const p of t.params) if (p.description) out.push(` * @param ${p.name} - ${p.description}`);
      if (o.returns && t.returns_description) out.push(` * @returns ${t.returns_description}`);
      out.push(" */");
    }
    const args = orderedParams(t).map((p) => tsParam(t, p, o)).join(", ");
    const ret = o.returns && t.returns ? tsType(t.returns) : "unknown";
    out.push(`declare function ${t.name}(${args}): ${ret};`);
    out.push("");
  }
  return out.join("\n").trimEnd();
}
