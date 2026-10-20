/* xml_schema: port of XMLTools in toolform/formats/markup.py. */

import type { ParamIR, ToolIR } from "../tools";
import { isSet } from "../tools";
import { pyStr, xmlEscape, type RenderOptions } from "./common";

const x = (v: unknown) => xmlEscape(pyStr(v));

function paramXml(p: ParamIR, o: RenderOptions, indent: string): string[] {
  const out = [`${indent}<parameter name="${x(p.name)}" type="${p.type.kind}" required="${p.required ? "true" : "false"}">`];
  if (o.descriptions && p.description) out.push(`${indent}  <description>${x(p.description)}</description>`);
  if (p.type.kind === "enum") out.push(`${indent}  <enum>` + (p.type.enum_values ?? []).map(x).join(", ") + "</enum>");
  if (p.type.kind === "array" && p.type.item) out.push(`${indent}  <items type="${p.type.item.kind}"/>`);
  if (p.type.kind === "object" && p.type.fields?.length) {
    out.push(`${indent}  <fields>`);
    for (const f of p.type.fields) out.push(...paramXml(f, o, indent + "    "));
    out.push(`${indent}  </fields>`);
  }
  if (o.defaults && isSet(p.default)) out.push(`${indent}  <default>${x(p.default)}</default>`);
  out.push(`${indent}</parameter>`);
  return out;
}

export function renderXml(tools: ToolIR[], o: RenderOptions): string {
  const out = ["<tools>"];
  for (const t of tools) {
    out.push("  <tool>");
    out.push(`    <name>${x(t.name)}</name>`);
    if (o.descriptions && t.description) out.push(`    <description>${x(t.description)}</description>`);
    out.push("    <parameters>");
    for (const p of t.params) out.push(...paramXml(p, o, "      "));
    out.push("    </parameters>");
    if (o.returns && t.returns_description) out.push(`    <returns>${x(t.returns_description)}</returns>`);
    out.push("  </tool>");
  }
  out.push("</tools>");
  return out.join("\n");
}
