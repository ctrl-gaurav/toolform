/* natural_language: port of NaturalLanguage in toolform/formats/prose.py. */

import type { ToolIR, TypeIR } from "../tools";
import { isSet } from "../tools";
import { optionalParams, pyStr, requiredParams, rstripDots, type RenderOptions } from "./common";

function typePhrase(t: TypeIR | null | undefined): string {
  if (!t) return "a value";
  switch (t.kind) {
    case "array":
      return t.item ? `a list of ${typePhrase(t.item)}s` : "a list";
    case "object":
      if (t.fields?.length) return "a group of values containing " + t.fields.map((f) => `${f.name} (${typePhrase(f.type)})`).join(", ");
      return "a group of values";
    case "enum":
      return "one of " + (t.enum_values ?? []).map((v) => `"${pyStr(v)}"`).join(", ");
    case "union":
      return (t.union_of ?? []).map(typePhrase).join(" or ");
    case "string":
      return "a piece of text";
    case "integer":
      return "a whole number";
    case "number":
      return "a number";
    case "boolean":
      return "true or false";
    case "null":
      return "nothing";
    case "any":
      return "any value";
    default:
      return "a value";
  }
}

function constraintPhrase(t: TypeIR): string {
  const c = t.constraints ?? {};
  const bits: string[] = [];
  if (isSet(c.minimum) && isSet(c.maximum)) bits.push(`between ${pyStr(c.minimum)} and ${pyStr(c.maximum)}`);
  else if (isSet(c.minimum)) bits.push(`at least ${pyStr(c.minimum)}`);
  else if (isSet(c.maximum)) bits.push(`at most ${pyStr(c.maximum)}`);
  if (isSet(c.max_length)) bits.push(`no longer than ${pyStr(c.max_length)} characters`);
  if (c.format) bits.push(`in ${c.format} format`);
  return bits.join(", ");
}

function join(items: string[]): string {
  if (!items.length) return "";
  if (items.length === 1) return items[0];
  return items.slice(0, -1).join(", ") + ", and " + items[items.length - 1];
}

export function renderNaturalLanguage(tools: ToolIR[], o: RenderOptions): string {
  const out: string[] = [];
  tools.forEach((t, idx) => {
    const para = [`${idx + 1}. The tool ${t.name}.`];
    if (o.descriptions && t.description) para.push(rstripDots(t.description) + ".");
    const req = requiredParams(t);
    const opt = optionalParams(t);
    if (req.length) {
      const bits = req.map((p) => {
        let s = `${p.name}, which is ${typePhrase(p.type)}`;
        // The Python renderer checks opts.constraints here; constraints are
        // already stripped from the IR when that option is off.
        const cp = constraintPhrase(p.type);
        if (o.constraints && cp) s += ` ${cp}`;
        if (o.descriptions && p.description) s += ` (${rstripDots(p.description)})`;
        return s;
      });
      para.push("It always needs " + join(bits) + ".");
    }
    if (opt.length) {
      const bits = opt.map((p) => {
        let s = `${p.name}, which is ${typePhrase(p.type)}`;
        if (o.defaults && isSet(p.default)) s += ` and defaults to ${pyStr(p.default)}`;
        if (o.descriptions && p.description) s += ` (${rstripDots(p.description)})`;
        return s;
      });
      para.push("You may also give " + join(bits) + ".");
    }
    if (o.returns && t.returns_description) para.push(`It gives back ${rstripDots(t.returns_description)}.`);
    out.push(para.join(" "));
    out.push("");
  });
  return out.join("\n").trimEnd();
}
