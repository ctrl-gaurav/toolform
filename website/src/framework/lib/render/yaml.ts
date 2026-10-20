/* yaml_schema: port of YAMLSchema in toolform/formats/yaml_family.py.
 *
 * The Python renderer calls yaml.safe_dump(obj, sort_keys=False,
 * default_flow_style=False, indent=2, width=88, allow_unicode=True). That
 * emitter decides quoting from a scan of each string and folds long plain
 * strings at column 88, so a faithful port has to follow the same state
 * machine. This is a port of the parts of PyYAML's Emitter that block-style
 * output of plain data (dicts, lists, strings, numbers, booleans, null)
 * reaches: analyze_scalar, choose_scalar_style, the three scalar writers,
 * write_indent and write_indicator, and the implicit resolvers.
 */

import type { ToolIR } from "../tools";
import { pyNumber, toolToJsonSchema, type RenderOptions } from "./common";

const BREAKS = "\n\x85\u2028\u2029";
const SPACE_OR_BREAK = "\0 \t\r\n\x85\u2028\u2029";

const RESOLVERS: RegExp[] = [
  /^(?:yes|Yes|YES|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF)$/,
  /^(?:[-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+][0-9]+)?|\.[0-9][0-9_]*(?:[eE][-+][0-9]+)?|[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]*|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$/,
  /^(?:[-+]?0b[0-1_]+|[-+]?0[0-7_]+|[-+]?(?:0|[1-9][0-9_]*)|[-+]?0x[0-9a-fA-F_]+|[-+]?[1-9][0-9_]*(?::[0-5]?[0-9])+)$/,
  /^(?:<<)$/,
  /^(?:~|null|Null|NULL|)$/,
  /^(?:[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]|[0-9][0-9][0-9][0-9]-[0-9][0-9]?-[0-9][0-9]?(?:[Tt]|[ \t]+)[0-9][0-9]?:[0-9][0-9]:[0-9][0-9](?:\.[0-9]*)?(?:[ \t]*(?:Z|[-+][0-9][0-9]?(?::[0-9][0-9])?))?)$/,
  /^(?:=)$/,
  /^(?:!|&|\*)$/,
];

/** Would PyYAML read this plain text back as a string? */
function resolvesToStr(s: string): boolean {
  // Python's `$` also matches before one trailing newline.
  const t = s.endsWith("\n") ? s.slice(0, -1) : s;
  return !RESOLVERS.some((r) => r.test(s) || (t !== s && r.test(t)));
}

interface Analysis {
  empty: boolean;
  multiline: boolean;
  allowFlowPlain: boolean;
  allowBlockPlain: boolean;
  allowSingleQuoted: boolean;
}

function isPrintableUnicode(cp: number): boolean {
  return cp === 0x85 || (cp >= 0xa0 && cp <= 0xd7ff) || (cp >= 0xe000 && cp <= 0xfffd) || (cp >= 0x10000 && cp < 0x10ffff);
}

function analyze(chars: string[]): Analysis {
  if (chars.length === 0) {
    return { empty: true, multiline: false, allowFlowPlain: false, allowBlockPlain: true, allowSingleQuoted: true };
  }
  const scalar = chars.join("");
  let blockIndicators = false;
  let flowIndicators = false;
  let lineBreaks = false;
  let specialCharacters = false;
  let leadingSpace = false;
  let leadingBreak = false;
  let trailingSpace = false;
  let trailingBreak = false;
  let breakSpace = false;
  let spaceBreak = false;
  if (scalar.startsWith("---") || scalar.startsWith("...")) {
    blockIndicators = true;
    flowIndicators = true;
  }
  let precededByWhitespace = true;
  let followedByWhitespace = chars.length === 1 || SPACE_OR_BREAK.includes(chars[1]);
  let previousSpace = false;
  let previousBreak = false;
  for (let index = 0; index < chars.length; index++) {
    const ch = chars[index];
    if (index === 0) {
      if ("#,[]{}&*!|>'\"%@`".includes(ch)) {
        flowIndicators = true;
        blockIndicators = true;
      }
      if (ch === "?" || ch === ":") {
        flowIndicators = true;
        if (followedByWhitespace) blockIndicators = true;
      }
      if (ch === "-" && followedByWhitespace) {
        flowIndicators = true;
        blockIndicators = true;
      }
    } else {
      if (",?[]{}".includes(ch)) flowIndicators = true;
      if (ch === ":") {
        flowIndicators = true;
        if (followedByWhitespace) blockIndicators = true;
      }
      if (ch === "#" && precededByWhitespace) {
        flowIndicators = true;
        blockIndicators = true;
      }
    }
    if (BREAKS.includes(ch)) lineBreaks = true;
    const cp = ch.codePointAt(0)!;
    if (!(ch === "\n" || (cp >= 0x20 && cp <= 0x7e))) {
      if (!(isPrintableUnicode(cp) && cp !== 0xfeff)) specialCharacters = true;
    }
    if (ch === " ") {
      if (index === 0) leadingSpace = true;
      if (index === chars.length - 1) trailingSpace = true;
      if (previousBreak) breakSpace = true;
      previousSpace = true;
      previousBreak = false;
    } else if (BREAKS.includes(ch)) {
      if (index === 0) leadingBreak = true;
      if (index === chars.length - 1) trailingBreak = true;
      if (previousSpace) spaceBreak = true;
      previousSpace = false;
      previousBreak = true;
    } else {
      previousSpace = false;
      previousBreak = false;
    }
    precededByWhitespace = SPACE_OR_BREAK.includes(ch);
    followedByWhitespace = index + 2 >= chars.length || SPACE_OR_BREAK.includes(chars[index + 2]);
  }
  let allowFlowPlain = true;
  let allowBlockPlain = true;
  let allowSingleQuoted = true;
  if (leadingSpace || leadingBreak || trailingSpace || trailingBreak) allowFlowPlain = allowBlockPlain = false;
  if (breakSpace) allowFlowPlain = allowBlockPlain = allowSingleQuoted = false;
  if (spaceBreak || specialCharacters) allowFlowPlain = allowBlockPlain = allowSingleQuoted = false;
  if (lineBreaks) allowFlowPlain = allowBlockPlain = false;
  if (flowIndicators) allowFlowPlain = false;
  if (blockIndicators) allowBlockPlain = false;
  return { empty: false, multiline: lineBreaks, allowFlowPlain, allowBlockPlain, allowSingleQuoted };
}

const ESCAPES: Record<string, string> = {
  "\0": "0", "\x07": "a", "\x08": "b", "\x09": "t", "\x0A": "n", "\x0B": "v", "\x0C": "f",
  "\x0D": "r", "\x1B": "e", '"': '"', "\\": "\\", "\x85": "N", "\xA0": "_", "\u2028": "L", "\u2029": "P",
};

class Emitter {
  out = "";
  column = 0;
  whitespace = true;
  indention = true;
  indent: number | null = null;
  indents: (number | null)[] = [];
  flowLevel = 0;
  bestIndent: number;
  bestWidth: number;
  simpleKeyContext = false;
  mappingContext = false;

  constructor(indent: number, width: number) {
    this.bestIndent = indent > 1 && indent < 10 ? indent : 2;
    this.bestWidth = width > this.bestIndent * 2 ? width : 80;
  }

  write(s: string) {
    this.out += s;
  }
  len(s: string) {
    return Array.from(s).length;
  }

  increaseIndent(flow = false, indentless = false) {
    this.indents.push(this.indent);
    if (this.indent === null) this.indent = flow ? this.bestIndent : 0;
    else if (!indentless) this.indent += this.bestIndent;
  }
  popIndent() {
    this.indent = this.indents.pop() ?? null;
  }

  writeIndicator(indicator: string, needWhitespace: boolean, whitespace = false, indention = false) {
    const data = this.whitespace || !needWhitespace ? indicator : " " + indicator;
    this.whitespace = whitespace;
    this.indention = this.indention && indention;
    this.column += this.len(data);
    this.write(data);
  }

  writeIndent() {
    const indent = this.indent ?? 0;
    if (!this.indention || this.column > indent || (this.column === indent && !this.whitespace)) this.writeLineBreak();
    if (this.column < indent) {
      this.whitespace = true;
      this.write(" ".repeat(indent - this.column));
      this.column = indent;
    }
  }

  writeLineBreak(data = "\n") {
    this.whitespace = true;
    this.indention = true;
    this.column = 0;
    this.write(data);
  }

  /* ---------------------------------------------------------------- nodes */

  node(v: unknown, ctx: { sequence?: boolean; mapping?: boolean; simpleKey?: boolean }) {
    this.mappingContext = !!ctx.mapping;
    this.simpleKeyContext = !!ctx.simpleKey;
    if (Array.isArray(v)) {
      if (this.flowLevel || v.length === 0) this.flowSequence(v);
      else this.blockSequence(v);
    } else if (v !== null && typeof v === "object") {
      const entries = Object.entries(v as Record<string, unknown>);
      if (this.flowLevel || entries.length === 0) this.flowMapping(entries);
      else this.blockMapping(entries);
    } else {
      this.scalar(v);
    }
  }

  flowSequence(items: unknown[]) {
    this.writeIndicator("[", true, true);
    this.flowLevel++;
    this.increaseIndent(true);
    items.forEach((it, i) => {
      if (i > 0) this.writeIndicator(",", false);
      if (this.column > this.bestWidth) this.writeIndent();
      this.node(it, { sequence: true });
    });
    this.popIndent();
    this.flowLevel--;
    this.writeIndicator("]", false);
  }

  flowMapping(entries: [string, unknown][]) {
    this.writeIndicator("{", true, true);
    this.flowLevel++;
    this.increaseIndent(true);
    entries.forEach(([k, val], i) => {
      if (i > 0) this.writeIndicator(",", false);
      if (this.column > this.bestWidth) this.writeIndent();
      this.node(k, { mapping: true, simpleKey: true });
      this.writeIndicator(":", false);
      this.node(val, { mapping: true });
    });
    this.popIndent();
    this.flowLevel--;
    this.writeIndicator("}", false);
  }

  blockSequence(items: unknown[]) {
    const indentless = this.mappingContext && !this.indention;
    this.increaseIndent(false, indentless);
    for (const it of items) {
      this.writeIndent();
      this.writeIndicator("-", true, false, true);
      this.node(it, { sequence: true });
    }
    this.popIndent();
  }

  blockMapping(entries: [string, unknown][]) {
    this.increaseIndent(false);
    for (const [k, val] of entries) {
      this.writeIndent();
      this.node(k, { mapping: true, simpleKey: true });
      this.writeIndicator(":", false);
      this.node(val, { mapping: true });
    }
    this.popIndent();
  }

  scalar(v: unknown) {
    let text: string;
    let implicit = true;
    if (v === null || v === undefined) text = "null";
    else if (typeof v === "boolean") text = v ? "true" : "false";
    else if (typeof v === "number") {
      text = pyNumber(v).toLowerCase();
      if (!Number.isInteger(v) && !text.includes(".") && text.includes("e")) text = text.replace("e", ".0e");
    } else {
      text = String(v);
      implicit = resolvesToStr(text);
    }
    this.increaseIndent(true);
    this.processScalar(text, implicit);
    this.popIndent();
  }

  processScalar(text: string, implicit: boolean) {
    const chars = Array.from(text);
    const a = analyze(chars);
    let style: "" | "'" | '"' = '"';
    const plainOk =
      implicit &&
      !(this.simpleKeyContext && (a.empty || a.multiline)) &&
      ((this.flowLevel && a.allowFlowPlain) || (!this.flowLevel && a.allowBlockPlain));
    if (plainOk) style = "";
    else if (a.allowSingleQuoted && !(this.simpleKeyContext && a.multiline)) style = "'";
    const split = !this.simpleKeyContext;
    if (style === "") this.writePlain(chars, split);
    else if (style === "'") this.writeSingleQuoted(chars, split);
    else this.writeDoubleQuoted(chars, split);
  }

  /* ---------------------------------------------------------------- writers */

  writePlain(text: string[], split: boolean) {
    if (!text.length) return;
    if (!this.whitespace) {
      this.column += 1;
      this.write(" ");
    }
    this.whitespace = false;
    this.indention = false;
    let spaces = false;
    let breaks = false;
    let start = 0;
    let end = 0;
    while (end <= text.length) {
      const ch = end < text.length ? text[end] : null;
      if (spaces) {
        if (ch !== " ") {
          if (start + 1 === end && this.column > this.bestWidth && split) {
            this.writeIndent();
            this.whitespace = false;
            this.indention = false;
          } else {
            const data = text.slice(start, end).join("");
            this.column += end - start;
            this.write(data);
          }
          start = end;
        }
      } else if (breaks) {
        if (ch === null || !BREAKS.includes(ch)) {
          if (text[start] === "\n") this.writeLineBreak();
          for (const br of text.slice(start, end)) this.writeLineBreak(br === "\n" ? "\n" : br);
          this.writeIndent();
          this.whitespace = false;
          this.indention = false;
          start = end;
        }
      } else if (ch === null || (" " + BREAKS).includes(ch)) {
        this.column += end - start;
        this.write(text.slice(start, end).join(""));
        start = end;
      }
      if (ch !== null) {
        spaces = ch === " ";
        breaks = BREAKS.includes(ch);
      }
      end++;
    }
  }

  writeSingleQuoted(text: string[], split: boolean) {
    this.writeIndicator("'", true);
    let spaces = false;
    let breaks = false;
    let start = 0;
    let end = 0;
    while (end <= text.length) {
      const ch = end < text.length ? text[end] : null;
      if (spaces) {
        if (ch === null || ch !== " ") {
          if (start + 1 === end && this.column > this.bestWidth && split && start !== 0 && end !== text.length) {
            this.writeIndent();
          } else {
            this.column += end - start;
            this.write(text.slice(start, end).join(""));
          }
          start = end;
        }
      } else if (breaks) {
        if (ch === null || !BREAKS.includes(ch)) {
          if (text[start] === "\n") this.writeLineBreak();
          for (const br of text.slice(start, end)) this.writeLineBreak(br === "\n" ? "\n" : br);
          this.writeIndent();
          start = end;
        }
      } else if (ch === null || (" " + BREAKS).includes(ch) || ch === "'") {
        if (start < end) {
          this.column += end - start;
          this.write(text.slice(start, end).join(""));
          start = end;
        }
      }
      if (ch === "'") {
        this.column += 2;
        this.write("''");
        start = end + 1;
      }
      if (ch !== null) {
        spaces = ch === " ";
        breaks = BREAKS.includes(ch);
      }
      end++;
    }
    this.writeIndicator("'", false);
  }

  writeDoubleQuoted(text: string[], split: boolean) {
    this.writeIndicator('"', true);
    let start = 0;
    let end = 0;
    while (end <= text.length) {
      const ch = end < text.length ? text[end] : null;
      const cp = ch === null ? 0 : ch.codePointAt(0)!;
      const printable = ch !== null && ((cp >= 0x20 && cp <= 0x7e) || (cp >= 0xa0 && cp <= 0xd7ff) || (cp >= 0xe000 && cp <= 0xfffd));
      if (ch === null || '"\\\x85\u2028\u2029\uFEFF'.includes(ch) || !printable) {
        if (start < end) {
          this.column += end - start;
          this.write(text.slice(start, end).join(""));
          start = end;
        }
        if (ch !== null) {
          let data: string;
          if (ESCAPES[ch] !== undefined) data = "\\" + ESCAPES[ch];
          else if (cp <= 0xff) data = "\\x" + cp.toString(16).toUpperCase().padStart(2, "0");
          else if (cp <= 0xffff) data = "\\u" + cp.toString(16).toUpperCase().padStart(4, "0");
          else data = "\\U" + cp.toString(16).toUpperCase().padStart(8, "0");
          this.column += data.length;
          this.write(data);
          start = end + 1;
        }
      }
      if (end > 0 && end < text.length - 1 && (ch === " " || start >= end) && this.column + (end - start) > this.bestWidth && split) {
        const data = text.slice(start, end).join("") + "\\";
        if (start < end) start = end;
        this.column += this.len(data);
        this.write(data);
        this.writeIndent();
        this.whitespace = false;
        this.indention = false;
        if (text[start] === " ") {
          this.column += 1;
          this.write("\\");
        }
      }
      end++;
    }
    this.writeIndicator('"', false);
  }
}

/** yaml.safe_dump(obj, sort_keys=False, indent, width, allow_unicode=True).rstrip() */
export function safeDump(obj: unknown, indent = 2, width = 88): string {
  const e = new Emitter(indent, width);
  e.node(obj, {});
  e.writeIndent();
  return e.out.trimEnd();
}

export function renderYaml(tools: ToolIR[], o: RenderOptions): string {
  const payload = tools.map((t) => toolToJsonSchema(t, "openai_flat", o.descriptions, o.returns));
  return safeDump(payload, o.indent, 88);
}
