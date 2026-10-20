/* json_schema_openai: port of OpenAIJSONSchema in toolform/formats/json_family.py. */

import type { ToolIR } from "../tools";
import { pyJson, toolToJsonSchema, type RenderOptions } from "./common";

export function renderJsonSchema(tools: ToolIR[], o: RenderOptions): string {
  const payload = tools.map((t) => toolToJsonSchema(t, "openai", o.descriptions, o.returns));
  // json.dumps(obj, indent=2, ensure_ascii=False), or compact when minified
  if (o.minify) return pyJson(payload, { itemSep: ",", keySep: ":", ensureAscii: false });
  return pyJson(payload, { indent: o.indent, ensureAscii: false });
}
