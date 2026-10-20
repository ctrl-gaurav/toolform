/* python_stub: port of PythonGoogleDocstring in toolform/formats/python_family.py. */

import type { ParamIR, ToolIR, TypeIR } from "../tools";
import { orderedParams, pyValue, type RenderOptions } from "./common";

function pyScalar(t: TypeIR): string {
  switch (t.kind) {
    case "string":
      return "str";
    case "integer":
      return "int";
    case "number":
      return "float";
    case "boolean":
      return "bool";
    case "object":
      return "dict[str, Any]";
    case "array":
      return "list[Any]";
    case "null":
      return "None";
    default:
      return "Any";
  }
}

export function pyType(t: TypeIR): string {
  if (t.kind === "object" && t.fields?.length) return "dict[str, Any]";
  if (t.kind === "array" && t.item) return `list[${pyType(t.item)}]`;
  if (t.kind === "enum") return "Literal[" + (t.enum_values ?? []).map(pyValue).join(", ") + "]";
  if (t.kind === "union") return (t.union_of ?? []).map(pyType).join(" | ");
  return pyScalar(t);
}

function signature(t: ToolIR, o: RenderOptions): string {
  const parts = orderedParams(t).map((p) => {
    const ann = pyType(p.type);
    if (p.required) return `${p.name}: ${ann}`;
    const def = o.defaults ? pyValue(p.default) : "None";
    return `${p.name}: ${ann} = ${def}`;
  });
  const ret = o.returns && t.returns ? pyType(t.returns) : "Any";
  return `def ${t.name}(${parts.join(", ")}) -> ${ret}:`;
}

function nestedNote(p: ParamIR): string {
  const t = p.type;
  if (t.kind === "object" && t.fields?.length) {
    return " Keys: " + t.fields.map((f) => `${f.name} (${f.type.kind}${f.required ? "" : ", optional"})`).join(", ") + ".";
  }
  if (t.kind === "array" && t.item && t.item.kind === "object") {
    return " Each item has keys: " + (t.item.fields ?? []).map((f) => f.name).join(", ") + ".";
  }
  return "";
}

export function renderPythonStub(tools: ToolIR[], o: RenderOptions): string {
  const out: string[] = [];
  for (const t of tools) {
    out.push(signature(t, o));
    if (o.descriptions) {
      out.push('    """' + (t.description || t.name));
      if (t.params.length) {
        out.push("");
        out.push("    Args:");
        for (const p of t.params) {
          const req = p.required ? "" : ", optional";
          out.push(`        ${p.name} (${pyType(p.type)}${req}): ${p.description ?? ""}${nestedNote(p)}`.trimEnd());
        }
      }
      if (o.returns && (t.returns || t.returns_description)) {
        out.push("");
        out.push("    Returns:");
        out.push(`        ${t.returns_description || "Result of the call."}`);
      }
      out.push('    """');
    }
    out.push("    ...");
    out.push("");
  }
  return out.join("\n").trimEnd();
}
