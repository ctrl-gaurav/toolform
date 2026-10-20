/* The description guard, a port of toolform.guard (rules.py, scan.py, clean.py).
 *
 * What it is for: in the study, one plain sentence written into one tool's
 * description was followed on 38.48 to 54.16% of turns in every format that
 * shows descriptions (tab_pressure), and a trust sentence in the system prompt
 * did not lower that (tab_injection_trust). The defence the evidence supports is
 * to keep instructions out of the description channel. This is a rule-based
 * detector for that. The study measured how often models follow hidden
 * instructions, not this detector. On a held-out set of 50 descriptions it
 * flagged 12 of 25 injected ones and 1 of 25 benign ones at high severity
 * (tests/framework/fixtures/guard_heldout.json in the package).
 *
 * The rules, the sentence splitter and the cleaning follow the Python module
 * line for line, and guard.test.ts checks every case of guard_cases.json (same
 * rule ids, severities and spans). Every pattern bridges at most GAP characters
 * and tool names are looked up in a prepared index, so a scan is linear in the
 * length of the text and does not grow with the size of the catalogue. One known gap: Python counts offsets in code
 * points and JavaScript in UTF-16 units, so spans after a character outside the
 * Basic Multilingual Plane (an emoji) differ by one per such character.
 */

import type { ParamIR, ToolIR, TypeIR } from "./tools";

export type Severity = "high" | "medium" | "low";

export interface Rule {
  id: string;
  name: string;
  severity: Severity;
  summary: string;
}

export const TOOL_DESC_LIMIT = 1500;
export const PARAM_DESC_LIMIT = 500;

export const RULES: Rule[] = [
  { id: "TS101", name: "hidden_instruction", severity: "high", summary: "An instruction addressed to the model. High when it has a target: a literal value, a tool to call, what to say, a secret, or words aimed at the model or at its other instructions. Medium for any other imperative, low for a restriction such as \"do not use this tool for math\"." },
  { id: "TS102", name: "sentinel_value", severity: "high", summary: "A sentence that assigns a literal value to an argument, such as a parameter name or a code like OVERRIDE-7731." },
  { id: "TS103", name: "calls_other_tool", severity: "high", summary: "The text names a tool of the catalogue next to a verb of calling. High when it also says first, before, also, then or instead, unless it states a prerequisite of this tool (\"call list_files before read_file\" on read_file); medium otherwise." },
  { id: "TS104", name: "schema_mismatch", severity: "medium", summary: "The text names an identifier that is not a parameter of this tool, nor a tool's name." },
  { id: "TS105", name: "secrecy_or_exfiltration", severity: "high", summary: "The text asks for secrecy, to send something to an address, or names a file that holds keys." },
  { id: "TS106", name: "role_markup", severity: "high", summary: "Chat-template or role markup inside tool metadata." },
  { id: "TS107", name: "urgency_or_authority", severity: "medium", summary: "Words that claim authority (this overrides, from the system, takes precedence): medium. IMPORTANT, CRITICAL or MANDATORY: medium beside an instruction, low alone." },
  { id: "TS108", name: "oversized_description", severity: "low", summary: `A tool description over ${TOOL_DESC_LIMIT.toLocaleString("en-US")} characters or a parameter description over ${PARAM_DESC_LIMIT} characters: room to hide text.` },
  { id: "TS109", name: "non_printing_text", severity: "high", summary: "Zero-width or bidirectional control characters, or an HTML comment: text a reader does not see." },
  { id: "TS110", name: "lookalike_letters", severity: "medium", summary: "A word that mixes Latin letters with Cyrillic or Greek ones, which can hide an instruction from a pattern. The other rules read such text with the lookalikes folded to Latin." },
];

const RULE_BY_ID = Object.fromEntries(RULES.map((r) => [r.id, r])) as Record<string, Rule>;

export const STRICTNESS: Record<string, Severity[]> = {
  lenient: ["high"],
  standard: ["high", "medium"],
  strict: ["high", "medium", "low"],
};
export type Strictness = "lenient" | "standard" | "strict";
export const SEVERITY_ORDER: Record<Severity, number> = { high: 0, medium: 1, low: 2 };

export interface Finding {
  rule_id: string;
  rule_name: string;
  severity: Severity;
  tool: string;
  field: string;
  text: string;
  start: number;
  end: number;
  message: string;
}

export interface KeptSpan {
  tool: string;
  field: string;
  rule_id: string;
  severity: Severity;
  text: string;
  reason: string;
}

export interface GuardReport {
  strictness: string;
  n_tools: number;
  findings: Finding[];
  flagged_tools: string[];
  counts: Record<Severity, number>;
  action: string;
  removed: { tool: string; field: string; text: string }[];
  kept: KeptSpan[];
  strip_at: Severity | null;
  tools?: ToolIR[] | null;
  evidence: { id: string; value: number; text: string }[];
  summary?: string;
}

/* ------------------------------------------------------------------ patterns (rules.py) */

const GAP = 120;
const HIDDEN_CLASS = "[\\u200b-\\u200f\\u202a-\\u202e\\u2066-\\u2069\\ufeff]";
const ACT_VERBS = "(?:call|invoke|use|run|set|pass|send|include|add|respond|reply|answer|output|write|tell|say|print)";
const CALL_VERBS = "(?:call|calls|calling|called|invoke|invokes|invoking|invoked|use|uses|using|run|runs|running|execute|executes|executing|trigger|triggers|triggering)";
const ORDER_WORDS = /\b(?:first|before|also|then|instead)\b/i;
const TS101_POSITIVE = "\\b(?:always|you must|you should|make sure|be sure to|instead|before (?:calling|using)|when (?:calling|using) this tool)\\b";
const TS101_NEGATIVE = "\\b(?:do not|don't|never)\\b";
const TS101_POSITIVE_ACT = new RegExp(`${TS101_POSITIVE}.{0,${GAP}}?\\b${ACT_VERBS}\\b`, "i");
const TS101_NEGATIVE_ACT = new RegExp(`${TS101_NEGATIVE}.{0,${GAP}}?\\b${ACT_VERBS}\\b`, "i");
const TS101_ADDRESSED = new RegExp(
  "\\bnote to the (?:assistant|model|ai|llm)\\b|" +
    "\\bthe (?:assistant|model|ai|llm) (?:should|must|will|needs to|has to)\\b|" +
    "\\b(?:regardless of|whatever) (?:what )?the user\\b|" +
    "\\bbefore (?:answering|responding|replying|handling)\\b|\\binstead of (?:answering|responding)\\b|" +
    `\\bwhen the user asks\\b.{0,${GAP}}?\\b(?:reply|respond|say|answer|tell)\\b|` +
    "\\bin your (?:reply|response|answer|final answer)\\b",
  "i",
);
const TS101_OVERRIDE = new RegExp(
  "\\b(?:ignore|disregard|forget)\\s+(?:(?:all|any|the|your|every)\\s+)?(?:previous|prior|above|earlier|other|preceding|system|original)\\b|" +
    "\\b(?:ignore|disregard|forget)\\s+(?:(?:all|any|every|your|these|those)\\s+)?(?:instructions?|rules?|guidelines?)\\b|" +
    "\\b(?:ignore|disregard)\\s+(?:the\\s+)?(?:user's|user)\\s+(?:question|request|message|instructions?)\\b|\\b(?:ignore|disregard)\\s+the\\s+request\\b",
  "i",
);
const TS101_TAMPER = /\b(?:append|add|include|insert|prepend|attach)\b.{0,80}?\b(?:to|in|into)\s+(?:every|each|all|your|the final)\s+(?:final\s+)?(?:answer|reply|response|message|output)s?\b/i;
const OUTPUT_VERBS = /\b(?:respond|reply|answer|say|tell|output|print)\b/i;
const SENSITIVE_WORDS = /\b(?:secret|secrets|password|passwords|credential|credentials|private key)\b/i;
const TS102 =
  /\b(?:set|pass|use|fill|put)\s+(?:the\s+)?[`'"]?(?<ident>[A-Za-z_][A-Za-z0-9_.-]*)[`'"]?(?:\s+(?:parameter|argument|field|value))?\s*(?:\bto\b|\bas\b|=|\bwith\b)\s*(?<value>'[^']*'|"[^"]*"|`[^`]*`|[^\s,;]+)/gi;
const SENTINEL = /^(?=[A-Z0-9_-]*\d)[A-Z0-9_-]{4,}$/;
const TS105_PHRASES = /\b(?:do not|don't|never) (?:tell|mention|inform|reveal|show)\b|\bwithout (?:asking|telling|confirming)\b|\bsecretly\b|\bkeep (?:this|it) (?:secret|hidden|confidential)\b/i;
const TS105_SILENT = new RegExp(`\\bsilently\\b.{0,${GAP}}?\\b${ACT_VERBS}\\b`, "i");
const URL_OR_EMAIL_SRC =
  "(?:https?://[^\\s'\"<>]+|(?<![A-Za-z0-9._%+\\-])[A-Za-z0-9._%+\\-]{1,64}@[A-Za-z0-9\\-]{1,63}(?:\\.[A-Za-z0-9\\-]{1,63}){0,8}\\.[A-Za-z]{2,24}(?![A-Za-z]))";
const TS105_EXFIL = new RegExp(
  "\\b(?:send|post|upload|forward|report|e-?mail|mail|share|copy|transmit|exfiltrate)[A-Za-z_]*\\b[^.;!?\\n]{0,200}?\\b(?:to|at)\\s+" + URL_OR_EMAIL_SRC,
  "i",
);
const TS105_PATHS = new RegExp(
  `\\b(?:read|cat|open|include|send|upload|print|copy|attach|return|output|show|leak)\\b.{0,${GAP}}?(?:~/\\.ssh\\b|\\bid_(?:rsa|dsa|ecdsa|ed25519)\\b|/etc/(?:passwd|shadow)\\b|\\.aws/credentials\\b|(?<![A-Za-z0-9_])\\.env\\b|\\.netrc\\b)`,
  "i",
);
// TS106: Python compiles the tokens case-sensitive and the two line patterns
// with (?im:...), so JavaScript needs two expressions.
const TS106_TOKENS = /<\|im_start\|>|<\|im_end\|>|<\|eot_id\|>|\[INST\]|<<SYS>>|<system>|<\/tool>|<\/tools>|<tool_call>/g;
const TS106_LINES = /^\s*(?:system|assistant)\s*:|^\s*###\s*instruction/gim;
const TS107_CAPS = /\b(?:IMPORTANT|CRITICAL|MANDATORY)\b|\bREQUIRED:/;
const TS107_PHRASES = /\bthis overrides\b|\boverrides? (?:all|any|every|other|previous)\b|\bhighest priority\b|\bfrom the system\b|\bdeveloper note\b|\bsystem (?:instruction|prompt|message)\b|\btakes? precedence\b/i;
const TS109_CHARS = new RegExp(HIDDEN_CLASS, "g");
const TS110_LETTERS = "A-Za-z\\u0370-\\u03ff\\u0400-\\u04ff\\u0500-\\u052f";
const TS110_MIXED = new RegExp(`(?=[${TS110_LETTERS}]*[A-Za-z])(?=[${TS110_LETTERS}]*[\\u0370-\\u03ff\\u0400-\\u04ff\\u0500-\\u052f])[${TS110_LETTERS}]+`, "g");
const AFTER = `(?=\\s|$|${HIDDEN_CLASS})`;
const BOUNDARY = new RegExp(`[.!?;]+${AFTER}|\\n`, "g");
const BOUNDARY_NO_SEMICOLON = new RegExp(`[.!?]+${AFTER}|\\n`, "g");

/** Cyrillic and Greek letters that look like Latin ones; one character to one, so offsets stay. */
export const CONFUSABLES: Record<string, string> = {
  "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c", "т": "t",
  "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "ԛ": "q", "ԝ": "w", "һ": "h", "ӏ": "l",
  "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
  "У": "Y", "Х": "X", "І": "I", "Ј": "J", "Ѕ": "S", "Ԁ": "D", "Ԛ": "Q", "Ԝ": "W",
  "α": "a", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t", "υ": "u", "χ": "x",
  "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O",
  "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
};
const CONFUSABLE_RE = new RegExp(`[${Object.keys(CONFUSABLES).join("")}]`, "g");

/** The text with Cyrillic and Greek lookalikes replaced by the Latin letter; same length. */
export function foldConfusables(text: string): string {
  return text.replace(CONFUSABLE_RE, (c) => CONFUSABLES[c] ?? c);
}

/** (start, end) of every HTML comment, in one pass (html_comments in rules.py). */
export function htmlComments(text: string): [number, number][] {
  const out: [number, number][] = [];
  let i = 0;
  for (;;) {
    const a = text.indexOf("<!--", i);
    if (a < 0) return out;
    const b = text.indexOf("-->", a + 4);
    if (b < 0) return out;
    out.push([a, b + 3]);
    i = b + 3;
  }
}

/** (start, end, sentence) spans, whitespace trimmed; split_sentences in rules.py. Removal passes semicolons=false. */
export function splitSentences(text: string, semicolons = true): [number, number, string][] {
  const spans: [number, number, string][] = [];
  const add = (start: number, end: number) => {
    const chunk = text.slice(start, end);
    if (!chunk.trim()) return;
    const lead = chunk.length - chunk.replace(/^\s+/, "").length;
    const trail = chunk.length - chunk.replace(/\s+$/, "").length;
    const s = start + lead;
    const e = end - trail;
    spans.push([s, e, text.slice(s, e)]);
  };
  let start = 0;
  for (const m of text.matchAll(semicolons ? BOUNDARY : BOUNDARY_NO_SEMICOLON)) {
    const idx = m.index ?? 0;
    const end = m[0] !== "\n" ? idx + m[0].length : idx;
    add(start, end);
    start = idx + m[0].length;
  }
  add(start, text.length);
  return spans;
}

/* ------------------------------------------------------------------ helpers (scan.py) */

export function canonicalName(name: string): string {
  return Array.from(String(name).toLowerCase())
    .filter((ch) => /[\p{L}\p{N}]/u.test(ch))
    .join("");
}

function canonSet(names: string[]): Set<string> {
  return new Set(names.filter(Boolean).map(canonicalName));
}

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function isSingleWord(name: string): boolean {
  return !/[_-]|[a-z][A-Z]/.test(name);
}

/** The catalogue's names and parameters, prepared once for every field of every tool (CatalogueIndex). */
export class CatalogueIndex {
  names: string[];
  order: Map<string, number>;
  multi = new Map<string, string[]>();
  single = new Map<string, string[]>();
  canonNames: Set<string>;
  otherParams: Set<string>;
  constructor(catalogueNames: string[] = [], otherParamNames: string[] = []) {
    this.names = catalogueNames.filter(Boolean);
    this.order = new Map(this.names.map((n, i) => [n, i]));
    for (const n of this.names) {
      const map = isSingleWord(n) ? this.single : this.multi;
      const key = isSingleWord(n) ? n.toLowerCase() : canonicalName(n);
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(n);
    }
    this.canonNames = canonSet(this.names);
    this.otherParams = canonSet(otherParamNames);
  }
}

const WORD = /[A-Za-z_][A-Za-z0-9_-]*/g;
const MARKED = /[`'"(\[](?<a>[^\s`'"()\[\]]{1,64})[`'")\]]|(?<![^\s`'"(\[])(?<b>[^\s`'"()\[\]]{1,64})(?=\s+(?:tool|function)\b)/gi;
const VERB_WORD = /[A-Za-z']+/g;
const CALL_VERB_FULL = new RegExp(`^${CALL_VERBS}$`, "i");

function nameHits(sentence: string, index: CatalogueIndex): Map<string, number[]> {
  const hits = new Map<string, number[]>();
  const push = (n: string, pos: number) => {
    if (!hits.has(n)) hits.set(n, []);
    hits.get(n)!.push(pos);
  };
  if (index.multi.size) {
    for (const m of sentence.matchAll(WORD)) for (const n of index.multi.get(canonicalName(m[0])) ?? []) push(n, m.index ?? 0);
  }
  if (index.single.size) {
    for (const m of sentence.matchAll(MARKED)) {
      const a = m.groups?.a;
      const word = a !== undefined ? a : m.groups!.b;
      const pos = a !== undefined ? m.index ?? 0 : m.index ?? 0;
      for (const n of index.single.get(word.toLowerCase()) ?? []) push(n, pos);
    }
  }
  return hits;
}

function lowerBound(xs: number[], x: number): number {
  let lo = 0;
  let hi = xs.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (xs[mid] < x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** A verb of calling within the six words before one of the positions. */
function called(positions: number[], verbs: [number, string][], starts: number[]): boolean {
  for (const pos of positions) {
    const i = lowerBound(starts, pos);
    if (verbs.slice(Math.max(0, i - 6), i).some(([, w]) => CALL_VERB_FULL.test(w))) return true;
  }
  return false;
}

function prerequisiteOf(sentence: string, tool: string): boolean {
  const own = ["this (?:tool|function)"];
  if (tool) own.push(escapeRe(tool));
  return new RegExp(`\\bbefore\\s+(?:(?:using|calling|invoking|running)\\s+)?(?:the\\s+)?(?:${own.join("|")})\\b`, "i").test(sentence);
}

// An identifier in quotes is a value ('left_click'), and one inside <|...|> is
// role markup (TS106); neither is taken for a parameter name.
const IDENT_SNAKE = /(?<![A-Za-z0-9_./@|'"-])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![A-Za-z0-9_@|'"-])/g;
const IDENT_CAMEL = /(?<![A-Za-z0-9_./@|'"-])[a-z]+(?:[A-Z][a-z0-9]+)+(?![A-Za-z0-9_@|'"-])/g;
const IDENT_TICK = /`([A-Za-z_][A-Za-z0-9_.-]*)`/g;
const URLISH = new RegExp(URL_OR_EMAIL_SRC, "g");
const URLISH_ONE = new RegExp(URL_OR_EMAIL_SRC);
const URLISH_FULL = new RegExp(`^${URL_OR_EMAIL_SRC}$`);
const QUOTED = /'[^'\s][^']{0,80}'|"[^"\s][^"]{0,80}"|`[^`\s][^`]{0,80}`/;
const SENTINEL_WORD = /(?<![A-Za-z0-9_-])(?=[A-Z0-9_-]*\d)(?=[A-Z0-9_-]*[A-Z])[A-Z0-9_-]{4,}(?![A-Za-z0-9_-])/;

function unknownIdentifiers(sentence: string, known: Set<string>): string[] {
  const urlSpans = Array.from(sentence.matchAll(URLISH)).map((m) => [m.index ?? 0, (m.index ?? 0) + m[0].length]);
  const inUrl = (i: number) => urlSpans.some(([a, b]) => a <= i && i < b);
  const found: string[] = [];
  for (const rx of [IDENT_TICK, IDENT_SNAKE, IDENT_CAMEL]) {
    for (const m of sentence.matchAll(rx)) {
      if (inUrl(m.index ?? 0)) continue;
      const ident = rx === IDENT_TICK ? m[1] : m[0];
      const parts = ident.split(".").filter(Boolean);
      if (!parts.length) continue;
      if (parts.some((p) => known.has(canonicalName(p)))) continue;
      if (["true", "false", "null", "none"].includes(ident.toLowerCase())) continue;
      if (!found.includes(ident)) found.push(ident);
    }
  }
  return found;
}

function literalValue(value: string): boolean {
  const v = value.trim();
  if (v.length >= 2 && v[0] === v[v.length - 1] && "'\"`".includes(v[0])) return true;
  if (/^-?\d+(?:\.\d+)?$/.test(v) || ["true", "false", "null", "none"].includes(v.toLowerCase())) return true;
  if (/^[A-Z][A-Z0-9_-]{2,}$/.test(v) || URLISH_FULL.test(v)) return true;
  return false;
}

function hasLiteral(sentence: string): boolean {
  return QUOTED.test(sentence) || SENTINEL_WORD.test(sentence) || URLISH_ONE.test(sentence);
}

function stripQuotes(v: string): string {
  return v.replace(/^['"`]+|['"`]+$/g, "");
}

function pyRepr(s: string): string {
  return s.includes("'") && !s.includes('"') ? `"${s}"` : `'${s}'`;
}

const TS101_MESSAGE: Record<Severity, string> = {
  high: "An instruction addressed to the model, with a target: it tells the model what to call, set, say or reveal. In the study, models followed one such planted sentence on 38.48 to 54.16% of turns in every format that shows descriptions.",
  medium: "An imperative with no value, tool or reply as its target. Often ordinary usage guidance; read it to be sure it asks nothing beyond what the tool needs.",
  low: 'A restriction on how to use the tool ("do not", "never"). Usually documentation; shown at strict strictness only.',
};

/* ------------------------------------------------------------------ scan_text */

export interface ScanContext {
  tool?: string;
  field?: string;
  /** Every tool name in the catalogue (TS103, TS104). */
  catalogueNames?: string[];
  /** This tool's parameter names at any depth (TS102, TS104). */
  paramNames?: string[];
  /** Other tools' parameter names, for TS102. */
  otherParamNames?: string[];
  /** More identifiers TS104 accepts, such as this tool's enum values. */
  knownWords?: string[];
  /** The catalogue prepared once; scanning a toolset passes it. */
  index?: CatalogueIndex;
}

/** Every finding on one field's text, at every severity. */
export function scanText(original: string, ctx: ScanContext = {}): Finding[] {
  if (!original) return [];
  const tool = ctx.tool ?? "";
  const field = ctx.field ?? "description";
  const text = foldConfusables(original);
  const out: Finding[] = [];
  const add = (ruleId: string, start: number, end: number, message: string, severity?: Severity) => {
    const r = RULE_BY_ID[ruleId];
    out.push({ rule_id: ruleId, rule_name: r.name, severity: severity ?? r.severity, tool, field, text: original.slice(start, end), start, end, message });
  };
  const sentences = splitSentences(text);
  const sentenceAt = (pos: number): [number, number] => {
    for (const [s, e] of sentences) if (s <= pos && pos < e) return [s, e];
    return [pos, pos + 1];
  };

  // TS109, TS110 and TS106 apply to every field, the name included.
  for (const m of text.matchAll(TS109_CHARS)) {
    const i = m.index ?? 0;
    add("TS109", i, i + m[0].length, `An invisible control character (U+${m[0].charCodeAt(0).toString(16).toUpperCase().padStart(4, "0")}). A reader does not see it, but it can hide or reorder text.`);
  }
  for (const [a, b] of htmlComments(text)) add("TS109", a, b, "An HTML comment: text a person reading a rendered page does not see.");
  if (text !== original) {
    for (const m of original.matchAll(TS110_MIXED)) {
      const i = m.index ?? 0;
      add("TS110", i, i + m[0].length, `The word ${pyRepr(m[0])} mixes Latin letters with Cyrillic or Greek ones that look the same. The guard read it with those letters folded to Latin.`);
    }
  }
  const markup = [...text.matchAll(TS106_TOKENS), ...text.matchAll(TS106_LINES)].sort((a, b) => (a.index ?? 0) - (b.index ?? 0));
  const marked = new Set<string>();
  for (const m of markup) {
    const [s, e] = sentenceAt(m.index ?? 0);
    const key = `${s}:${e}`;
    if (marked.has(key)) continue;
    marked.add(key);
    add("TS106", s, e, `Chat-template or role markup (${pyRepr(m[0].trim())}) inside tool metadata. It can make the text read as a message from the system or the assistant.`);
  }
  if (field === "name") return ordered(out);

  const idx = ctx.index ?? new CatalogueIndex(ctx.catalogueNames ?? [], ctx.otherParamNames ?? []);
  const params = canonSet(ctx.paramNames ?? []);
  const allParams = new Set([...params, ...idx.otherParams]);
  const known = new Set([...params, ...idx.canonNames, ...canonSet([tool]), ...canonSet(ctx.knownWords ?? [])]);

  for (const [s, e, sent] of sentences) {
    const hits = nameHits(sent, idx);
    const verbs: [number, string][] = hits.size ? Array.from(sent.matchAll(VERB_WORD), (m) => [m.index ?? 0, m[0]] as [number, string]) : [];
    const starts = verbs.map(([p]) => p);
    const prerequisite = prerequisiteOf(sent, tool);
    const calledBy = new Map<string, boolean>();
    for (const [n, pos] of hits) calledBy.set(n, called(pos, verbs, starts));
    const otherTool = Array.from(calledBy).some(([n, ok]) => ok && n !== tool);

    // TS101: an instruction, graded by its target.
    let severity: Severity | null = null;
    if (TS101_ADDRESSED.test(sent) || TS101_OVERRIDE.test(sent) || TS101_TAMPER.test(sent)) severity = "high";
    else if (TS101_POSITIVE_ACT.test(sent)) {
      const target = hasLiteral(sent) || OUTPUT_VERBS.test(sent) || SENSITIVE_WORDS.test(sent) || (otherTool && !prerequisite);
      severity = target ? "high" : "medium";
    } else if (TS101_NEGATIVE_ACT.test(sent)) severity = "low";
    if (severity) add("TS101", s, e, TS101_MESSAGE[severity], severity);

    for (const m of sent.matchAll(TS102)) {
      const ident = m.groups!.ident;
      let value = m.groups!.value;
      if (!"'\"`".includes(value[0])) value = value.replace(/[.!?)]+$/, "");
      const sentinel = SENTINEL.test(stripQuotes(value));
      if (sentinel || (allParams.has(canonicalName(ident)) && literalValue(value))) {
        add("TS102", s, e, `The sentence assigns the value ${value} to ${pyRepr(ident)}. A value the user never asked for, written into a call, is the argument hijack the study measured.`);
        break;
      }
    }

    const order = ORDER_WORDS.test(sent);
    const byOrder = Array.from(hits.keys()).sort((a, b) => (idx.order.get(a) ?? 0) - (idx.order.get(b) ?? 0));
    for (const name of byOrder) {
      if (!calledBy.get(name)) continue;
      if (name === tool) {
        if (order && !prerequisite) {
          add("TS103", s, e, `The text tells the model to call this tool (${name}) before or besides what the user asked.`, "high");
          break;
        }
        continue;
      }
      const what = order && prerequisite ? " as a prerequisite of this tool" : "";
      add("TS103", s, e, `The text tells the model to call another tool (${name})${what}.`, order && !prerequisite ? "high" : "medium");
      break;
    }

    const unknown = unknownIdentifiers(sent, known);
    if (unknown.length) {
      add("TS104", s, e, `The text names ${unknown.slice(0, 4).map(pyRepr).join(", ")}, which is not a parameter of this tool nor a tool in the catalogue.`);
    }
    if (TS105_PHRASES.test(sent) || TS105_SILENT.test(sent) || TS105_EXFIL.test(sent) || TS105_PATHS.test(sent)) {
      add("TS105", s, e, "The text asks for secrecy, for data to be sent to an address, or names a file that holds keys.");
    }
    if (TS107_PHRASES.test(sent)) {
      add("TS107", s, e, "The text claims authority over other instructions, a common frame for an injected instruction.");
    } else if (TS107_CAPS.test(sent)) {
      const loud = severity !== null && severity !== "low";
      add("TS107", s, e, loud ? "The text claims urgency beside an instruction." : "The text uses an urgency word. Alone it is usually emphasis; shown at strict strictness only.", loud ? "medium" : "low");
    }
  }

  const limit = field === "description" ? TOOL_DESC_LIMIT : field.startsWith("param:") ? PARAM_DESC_LIMIT : null;
  const len = Array.from(text).length;
  if (limit !== null && len > limit) {
    add("TS108", 0, text.length, `The text is ${len.toLocaleString("en-US")} characters, over the ${limit.toLocaleString("en-US")} this guard allows for this field (a heuristic threshold). Long text leaves room to hide an instruction. Stripping never removes it; review it by hand.`);
  }
  return ordered(out);
}

function ordered(fs: Finding[]): Finding[] {
  return fs.sort((a, b) => a.start - b.start || (a.rule_id < b.rule_id ? -1 : a.rule_id > b.rule_id ? 1 : 0));
}

/* ------------------------------------------------------------------ tools */

function* walkParams(params: ParamIR[], prefix = ""): Generator<[string, ParamIR]> {
  for (const p of params) {
    const path = prefix ? `${prefix}.${p.name}` : p.name;
    yield [path, p];
    yield* walkType(p.type, path);
  }
}

function* walkType(t: TypeIR | null | undefined, path: string): Generator<[string, ParamIR]> {
  if (!t) return;
  if (t.fields?.length) yield* walkParams(t.fields, path);
  if (t.item) yield* walkType(t.item, path + "[]");
  for (const u of t.union_of ?? []) yield* walkType(u, path);
}

function enumStrings(t: TypeIR): string[] {
  const out: string[] = [];
  const strs = (vals: unknown[] | undefined) => (vals ?? []).filter((v): v is string => typeof v === "string");
  if (t.kind === "enum") out.push(...strs(t.enum_values));
  for (const u of t.union_of ?? []) out.push(...enumStrings(u));
  if (t.item && t.item.kind === "enum") out.push(...strs(t.item.enum_values));
  return out;
}

function* walkAnnotations(value: unknown, key: string): Generator<[string, string]> {
  if (typeof value === "string") yield [key, value];
  else if (Array.isArray(value)) for (const [i, v] of value.entries()) yield* walkAnnotations(v, `${key}[${i}]`);
  else if (value && typeof value === "object") for (const [k, v] of Object.entries(value)) yield* walkAnnotations(v, key ? `${key}.${k}` : k);
}

/** Every scanned (field, text) of one tool, in scan order. */
export function toolFields(tool: ToolIR): [string, string][] {
  const fields: [string, string][] = [
    ["name", tool.name],
    ["description", tool.description],
    ["returns_description", tool.returns_description ?? ""],
  ];
  for (const [path, p] of walkParams(tool.params)) {
    fields.push([`param:${path}`, p.description ?? ""]);
    for (const v of enumStrings(p.type)) fields.push([`enum:${path}`, v]);
    if (typeof p.default === "string") fields.push([`default:${path}`, p.default]);
    if (typeof p.example === "string") fields.push([`example:${path}`, p.example]);
  }
  for (const [key, text] of walkAnnotations(tool.annotations ?? {}, "")) fields.push([`annotation:${key}`, text]);
  return fields.filter(([, t]) => !!t);
}

export function paramNamesOf(tool: ToolIR): string[] {
  return Array.from(walkParams(tool.params), ([, p]) => p.name);
}

export function scanTool(tool: ToolIR, catalogueNames: string[] = [], catalogueParams: string[] = [], index?: CatalogueIndex): Finding[] {
  const params = paramNamesOf(tool);
  const enums = Array.from(walkParams(tool.params)).flatMap(([, p]) => enumStrings(p.type));
  const names = catalogueNames.length ? catalogueNames : [tool.name];
  const idx = index ?? new CatalogueIndex(names, catalogueParams);
  const out: Finding[] = [];
  for (const [field, text] of toolFields(tool)) {
    out.push(...scanText(text, { tool: tool.name, field, catalogueNames: names, paramNames: params, otherParamNames: catalogueParams, knownWords: enums, index: idx }));
  }
  return out;
}

const GUARD_EVIDENCE = [
  { id: "injection_min", value: 38.48, text: "hidden instruction followed, lowest format that shows a description (tab_pressure)" },
  { id: "injection_max", value: 54.16, text: "hidden instruction followed, highest format that shows a description (tab_pressure)" },
  { id: "trust_line_sentinel", value: -0.35, text: "effect of a trust sentence in the system prompt (tab_injection_trust)" },
  { id: "hijack_schema_valid", value: 58.1, text: "followed hijacks that still pass schema validation" },
];

export function scanToolset(tools: ToolIR[], strictness: Strictness = "standard"): GuardReport {
  const keep = new Set(STRICTNESS[strictness] ?? STRICTNESS.standard);
  const names = tools.map((t) => t.name);
  const allParams = Array.from(new Set(tools.flatMap(paramNamesOf))).sort();
  const index = new CatalogueIndex(names, allParams);
  const findings: Finding[] = [];
  for (const t of tools) findings.push(...scanTool(t, names, allParams, index).filter((f) => keep.has(f.severity)));
  const flagged = names.filter((n) => findings.some((f) => f.tool === n));
  const counts: Record<Severity, number> = { high: 0, medium: 0, low: 0 };
  for (const f of findings) counts[f.severity]++;
  return { strictness, n_tools: tools.length, findings, flagged_tools: flagged, counts, action: "report", removed: [], kept: [], strip_at: null, tools, evidence: GUARD_EVIDENCE };
}

export function maxSeverity(r: GuardReport): Severity | null {
  if (r.counts.high) return "high";
  if (r.counts.medium) return "medium";
  if (r.counts.low) return "low";
  return null;
}

/* ------------------------------------------------------------------ cleaning (clean.py) */

export type GuardAction = "report" | "strip" | "drop_descriptions";
const NOT_STRIPPED = new Set(["TS108", "TS110"]);
const EXACT = new Set(["TS109"]);
const KEEP_NOTE = " It was not removed, because removing it would change the schema.";
const KEEP_REASONS: Record<string, string> = {
  schema: "an enum value, default or name: removing it would change the schema; fix or drop the tool by hand",
  TS108: "the finding is about the text's size, not words in it; review it by hand",
  TS110: "lookalike letters are reported, not rewritten; review the text by hand",
};

function tidy(text: string): string {
  return text.replace(/[ \t]{2,}/g, " ").replace(/\n{3,}/g, "\n\n").replace(/\s+([.,;:!?])/g, "$1").trim();
}

function mergeSpans(spans: [number, number][]): [number, number][] {
  const merged: [number, number][] = [];
  for (const [s, e] of [...spans].sort((a, b) => a[0] - b[0] || a[1] - b[1])) {
    if (merged.length && s <= merged[merged.length - 1][1]) merged[merged.length - 1][1] = Math.max(merged[merged.length - 1][1], e);
    else merged.push([s, e]);
  }
  return merged;
}

function cut(text: string, spans: [number, number][]): string {
  let out = text;
  for (const [s, e] of [...new Map(spans.map((x) => [`${x[0]}:${x[1]}`, x])).values()].sort((a, b) => b[0] - a[0])) out = out.slice(0, s) + " " + out.slice(e);
  return out;
}

/** Each span widened to the full sentences it touches (no split at ";"). */
export function wholeSentences(text: string, spans: [number, number][]): [number, number][] {
  const full = splitSentences(text, false);
  return spans.map(([s, e]) => {
    const cover = full.filter(([a, b]) => a < e && s < b);
    return [Math.min(s, ...cover.map(([a]) => a)), Math.max(e, ...cover.map(([, b]) => b))] as [number, number];
  });
}

/** Remove the spans and every invisible character; the new text and what was removed. */
export function cleanText(text: string, spans: [number, number][]): { text: string; removed: string[] } {
  const merged = mergeSpans(spans);
  const removed = merged.map(([s, e]) => text.slice(s, e));
  const out = cut(text, merged);
  const comments = htmlComments(out);
  const cleaned = cut(out, comments).replace(TS109_CHARS, "");
  if (cleaned !== out) {
    const found: [number, string][] = comments.map(([a, b]) => [a, out.slice(a, b)]);
    for (const m of out.matchAll(TS109_CHARS)) {
      const i = m.index ?? 0;
      if (!comments.some(([a, b]) => a <= i && i < b)) found.push([i, m[0]]);
    }
    for (const [, t] of found.sort((a, b) => a[0] - b[0])) removed.push(t);
  }
  return { text: merged.length || cleaned !== out ? tidy(cleaned) : text, removed };
}

/** For a single description: the text with the given findings' sentences removed, whole sentences at a time. */
export function stripSpans(text: string, spans: [number, number][]): string {
  return cleanText(text, wholeSentences(text, spans)).text;
}

type Edits = Record<string, { description?: string; example?: string | null }>;

function rebuildParams(params: ParamIR[], prefix: string, edits: Edits): ParamIR[] {
  return params.map((p) => {
    const path = prefix ? `${prefix}.${p.name}` : p.name;
    const np: ParamIR = { ...p, type: rebuildType(p.type, path, edits) };
    const e = edits[path];
    if (e && "description" in e) np.description = e.description;
    if (e && "example" in e) np.example = e.example ?? undefined;
    return np;
  });
}

function rebuildType(t: TypeIR, path: string, edits: Edits): TypeIR {
  const nt: TypeIR = { ...t };
  if (t.fields?.length) nt.fields = rebuildParams(t.fields, path, edits);
  if (t.item) nt.item = rebuildType(t.item, path + "[]", edits);
  if (t.union_of?.length) nt.union_of = t.union_of.map((u) => rebuildType(u, path, edits));
  return nt;
}

function setAnnotation(ann: unknown, keys: string[], value: string): unknown {
  if (!keys.length) return value;
  const [head, ...rest] = keys;
  const m = head.match(/^(.*?)\[(\d+)\]$/);
  if (ann && typeof ann === "object" && !Array.isArray(ann)) {
    const o = ann as Record<string, unknown>;
    if (m && m[1] in o && Array.isArray(o[m[1]])) {
      const lst = [...(o[m[1]] as unknown[])];
      lst[Number(m[2])] = setAnnotation(lst[Number(m[2])], rest, value);
      return { ...o, [m[1]]: lst };
    }
    if (head in o) return { ...o, [head]: setAnnotation(o[head], rest, value) };
  }
  return ann;
}

const isKept = (field: string) => field === "name" || field.startsWith("enum:") || field.startsWith("default:");

function keptSpan(f: Finding, reason: string): KeptSpan {
  return { tool: f.tool, field: f.field, rule_id: f.rule_id, severity: f.severity, text: f.text, reason: KEEP_REASONS[reason] };
}

function stripTool(tool: ToolIR, findings: Finding[], removed: GuardReport["removed"], kept: KeptSpan[]): ToolIR {
  const byField = new Map<string, [number, number][]>();
  const exact = new Map<string, [number, number][]>();
  for (const f of findings) {
    if (NOT_STRIPPED.has(f.rule_id)) {
      kept.push(keptSpan(f, f.rule_id));
      continue;
    }
    if (isKept(f.field)) {
      if (!f.message.endsWith(KEEP_NOTE)) f.message += KEEP_NOTE;
      kept.push(keptSpan(f, "schema"));
      continue;
    }
    const map = EXACT.has(f.rule_id) ? exact : byField;
    if (!map.has(f.field)) map.set(f.field, []);
    map.get(f.field)!.push([f.start, f.end]);
  }
  // Invisible characters are deleted wherever they are, flagged or not.
  const fields = new Map(toolFields(tool));
  for (const [fld, text] of fields) {
    if (isKept(fld)) continue;
    if (new RegExp(HIDDEN_CLASS).test(text) || htmlComments(text).length) if (!byField.has(fld)) byField.set(fld, []);
  }
  for (const fld of exact.keys()) if (!byField.has(fld)) byField.set(fld, []);
  if (!byField.size) return tool;
  const edits: Edits = {};
  let desc = tool.description;
  let ret = tool.returns_description ?? "";
  let annotations: unknown = tool.annotations;
  for (const [fld, spans] of byField) {
    const text = fields.get(fld) ?? "";
    if (!text) continue;
    const { text: nt, removed: gone } = cleanText(text, [...wholeSentences(text, spans), ...(exact.get(fld) ?? [])]);
    for (const c of gone) removed.push({ tool: tool.name, field: fld, text: c.trim() || c });
    if (fld === "description") desc = nt;
    else if (fld === "returns_description") ret = nt;
    else if (fld.startsWith("param:")) (edits[fld.slice(6)] ??= {}).description = nt;
    else if (fld.startsWith("example:")) (edits[fld.slice(8)] ??= {}).example = nt || null;
    else if (fld.startsWith("annotation:")) annotations = setAnnotation(annotations, fld.slice(11).split("."), nt);
  }
  return { ...tool, description: desc, returns_description: ret, params: rebuildParams(tool.params, "", edits), annotations: annotations as Record<string, unknown> | undefined };
}

function withoutDescriptions(tool: ToolIR): ToolIR {
  const t = (ty: TypeIR): TypeIR => ({ ...ty, fields: ty.fields?.map(p), item: ty.item ? t(ty.item) : ty.item, union_of: ty.union_of?.map(t) });
  const p = (x: ParamIR): ParamIR => ({ ...x, description: "", example: undefined, type: t(x.type) });
  return { ...tool, description: "", returns_description: "", params: tool.params.map(p), examples: [] };
}

/** Apply the action; report (the default) changes nothing, strip takes findings at stripAt or above (high by default). */
export function cleanToolset(report: GuardReport, tools: ToolIR[], action: GuardAction = "report", scope: "flagged" | "all" = "flagged", stripAt: Severity = "high"): GuardReport {
  const removed: GuardReport["removed"] = [];
  const kept: KeptSpan[] = [];
  const findings = report.findings.map((f) => ({ ...f }));
  if (action === "report") return { ...report, findings, action, removed: [], kept: [], strip_at: null, tools };
  let out: ToolIR[];
  if (action === "strip") {
    out = tools.map((t) => stripTool(t, findings.filter((f) => f.tool === t.name && SEVERITY_ORDER[f.severity] <= SEVERITY_ORDER[stripAt]), removed, kept));
  } else {
    const flagged = new Set(report.flagged_tools);
    out = tools.map((t) => {
      if (scope !== "all" && !flagged.has(t.name)) return t;
      for (const [fld, text] of toolFields(t)) {
        if (fld === "description" || fld === "returns_description" || fld.startsWith("param:") || fld.startsWith("example:")) removed.push({ tool: t.name, field: fld, text });
      }
      return withoutDescriptions(t);
    });
  }
  return { ...report, findings, action, removed, kept, strip_at: action === "strip" ? stripAt : null, tools: out };
}

export function guard(tools: ToolIR[], strictness: Strictness = "standard", action: GuardAction = "report", scope: "flagged" | "all" = "flagged", stripAt: Severity = "high"): GuardReport {
  return cleanToolset(scanToolset(tools, strictness), tools, action, scope, stripAt);
}

export function ruleById(id: string): Rule | undefined {
  return RULE_BY_ID[id];
}
