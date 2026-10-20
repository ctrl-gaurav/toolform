/* The eight core renderers, ported from toolform.formats.
 *
 * Every statistical claim of the study is made on these eight formats. The
 * parity test renders every case in render_cases.json and compares the text
 * with what the Python renderers wrote, byte for byte after trimming trailing
 * spaces per line. The other 121 formats render only through the API.
 */

import type { ToolIR } from "../tools";
import { applyOptions, DEFAULT_OPTIONS, type RenderOptions } from "./common";
import { renderJsonMinimal } from "./jsonMinimal";
import { renderJsonSchema } from "./jsonSchema";
import { renderMarkdownTable } from "./markdownTable";
import { renderNaturalLanguage } from "./naturalLanguage";
import { PROTOCOL_INSTRUCTIONS, type CrossingProtocol } from "./protocols";
import { renderPythonStub } from "./pythonStub";
import { renderTypeScript } from "./typescript";
import { renderXml } from "./xml";
import { renderYaml } from "./yaml";

export { DEFAULT_OPTIONS, type RenderOptions } from "./common";

export const CORE_FORMATS = [
  "xml_schema",
  "natural_language",
  "python_stub",
  "json_schema_openai",
  "yaml_schema",
  "typescript",
  "markdown_table",
  "json_minimal",
] as const;
export type CoreFormat = (typeof CORE_FORMATS)[number];

export const CORE_FORMAT_LABELS: Record<CoreFormat, string> = {
  xml_schema: "XML",
  natural_language: "natural language",
  python_stub: "Python stub",
  json_schema_openai: "JSON Schema",
  yaml_schema: "YAML",
  typescript: "TypeScript",
  markdown_table: "Markdown table",
  json_minimal: "minimal schema",
};

export const DEFAULT_PROTOCOL: Record<CoreFormat, CrossingProtocol> = {
  xml_schema: "xml_call",
  natural_language: "nl_intent",
  python_stub: "python_call",
  json_schema_openai: "json_object",
  yaml_schema: "json_object",
  typescript: "json_object",
  markdown_table: "json_object",
  json_minimal: "json_object",
};

export function isCoreFormat(id: string): id is CoreFormat {
  return (CORE_FORMATS as readonly string[]).includes(id);
}

type Renderer = (tools: ToolIR[], o: RenderOptions) => string;

const RENDERERS: Record<CoreFormat, Renderer> = {
  xml_schema: renderXml,
  natural_language: renderNaturalLanguage,
  python_stub: renderPythonStub,
  json_schema_openai: renderJsonSchema,
  yaml_schema: renderYaml,
  typescript: renderTypeScript,
  markdown_table: renderMarkdownTable,
  json_minimal: (tools) => renderJsonMinimal(tools),
};

/** Render a tool list in one of the eight core formats. */
export function renderFormat(tools: ToolIR[], formatId: CoreFormat, options: Partial<RenderOptions> = {}): string {
  const o = { ...DEFAULT_OPTIONS, ...options };
  const prepared = tools.map((t) => applyOptions(t, o));
  return RENDERERS[formatId](prepared, o);
}

export function protocolInstructions(protocolId: CrossingProtocol): string {
  return PROTOCOL_INSTRUCTIONS[protocolId];
}
