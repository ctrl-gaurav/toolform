/* json_minimal: port of JSONMinimal in toolform/formats/json_family.py.
 * Names, parameter names, types, enums, nesting and top-level required flags;
 * no descriptions, constraints or defaults whatever the options say. */

import type { ToolIR, TypeIR } from "../tools";
import { pyJson } from "./common";

function flatKind(t: TypeIR): string {
  if (t.kind === "array") return "array";
  if (t.kind === "enum") return "enum";
  return t.kind;
}

function bareType(t: TypeIR): unknown {
  if (t.kind === "array") return t.item ? [bareType(t.item)] : ["any"];
  if (t.kind === "object") {
    const o: Record<string, unknown> = {};
    for (const f of t.fields ?? []) o[f.name] = bareType(f.type);
    return o;
  }
  if (t.kind === "enum") return [...(t.enum_values ?? [])];
  if (t.kind === "union") return (t.union_of ?? []).map(flatKind).join("|");
  return t.kind;
}

export function renderJsonMinimal(tools: ToolIR[]): string {
  const payload = tools.map((t) => {
    const params: Record<string, unknown> = {};
    const req: string[] = [];
    for (const p of t.params) {
      params[p.name] = bareType(p.type);
      if (p.required) req.push(p.name);
    }
    return { name: t.name, params, required: req };
  });
  return pyJson(payload, { itemSep: ",", keySep: ":", ensureAscii: false });
}
