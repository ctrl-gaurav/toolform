/* markdown_table: port of MarkdownTable in toolform/formats/tabular.py.
 * One row per parameter; the tool's description repeats on every row, which is
 * what the injection experiment measured. */

import type { ToolIR, TypeIR } from "../tools";
import { isSet } from "../tools";
import { pyStr, type RenderOptions } from "./common";

const HEADER = ["tool", "param", "type", "required", "default", "param_doc", "tool_doc"];

function flatType(t: TypeIR | null | undefined): string {
  if (!t) return "any";
  if (t.kind === "array") return t.item ? `${flatType(t.item)}[]` : "any[]";
  if (t.kind === "object") return "{" + (t.fields ?? []).map((f) => `${f.name}:${flatType(f.type)}`).join(",") + "}";
  if (t.kind === "enum") return "enum[" + (t.enum_values ?? []).map(pyStr).join("|") + "]";
  if (t.kind === "union") return (t.union_of ?? []).map(flatType).join("|");
  return t.kind;
}

const esc = (s: string) => s.replace(/\|/g, "\\|").replace(/\n/g, " ");

export function renderMarkdownTable(tools: ToolIR[], o: RenderOptions): string {
  const rows: string[][] = [];
  for (const t of tools) {
    for (const p of t.params) {
      rows.push([
        t.name,
        p.name,
        flatType(p.type),
        p.required ? "yes" : "no",
        o.defaults && isSet(p.default) ? pyStr(p.default) : "",
        o.descriptions ? p.description ?? "" : "",
        o.descriptions ? t.description : "",
      ]);
    }
    if (!t.params.length) rows.push([t.name, "", "", "", "", "", o.descriptions ? t.description : ""]);
  }
  const cols = HEADER.map((h, i) => [h, i] as const).filter(([h]) => o.descriptions || (h !== "param_doc" && h !== "tool_doc")).map(([, i]) => i);
  const head = cols.map((i) => HEADER[i]);
  const out = ["| " + head.join(" | ") + " |", "|" + head.map(() => "---").join("|") + "|"];
  for (const r of rows) out.push("| " + cols.map((i) => esc(r[i])).join(" | ") + " |");
  return out.join("\n");
}
