"""Prose response protocols and the intent adapter.

The natural-language arm needs a parser that turns "I'll look up the weather
in Paris in Celsius" into ``get_weather(city="Paris", unit="C")``. That parser
is a confound if we are not careful, so the design here is deliberate:

* The **strict adapter** is rule-based and schema-guided. It only ever fills
  arguments that the tool actually declares, and it reports which rule fired.
* The **LLM adapter** (``nl_intent_llm``) sends the same text to a small
  parsing model. It is used for the dual-parser ablation.
* Parse fidelity was measured separately on a labelled subset.

If the two adapters disagree on the conclusion, we say so rather than picking
the flattering one.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from ..ir import ParamIR, ToolCall, ToolIR, ToolUniverse, TypeKind
from ..ir.types import canonical_name
from .base import (
    CallProtocol,
    ParseResult,
    ProtocolMeta,
    calls_from_json,
    declares_no_call,
    register_protocol,
    strip_fences,
    strip_reasoning,
    try_json,
)
from .structure import (
    coerce_text_value,
    loose_param,
    name_variants,
    recover_structure,
)

# --------------------------------------------------------------------------- #
# rule-based intent adapter
# --------------------------------------------------------------------------- #

# A value runs to the next comma, semicolon or newline. A period only ends it
# when a sentence ends there — otherwise `11.5` becomes `11` and
# `/reports/q1.md` becomes `/reports/q1`, which is a parser bug being scored as
# a model error.
#
# The period must be excluded from the general character class as well as
# handled by the guarded branch. Written as `[^\n,;]` it already matched `.`,
# so the lookahead never ran and a value swallowed the rest of the paragraph:
# `shared_with: ursula. Put it in reports` came back as the whole sentence.
_VAL = r'"[^"]*"|\'[^\']*\'|\[[^\]]*\]|\{{[^}}]*\}}|(?:[^\n,;.]|\.(?!\s|$))+'

_ASSIGN_PATTERNS = [
    # name = value / name: value
    re.compile(r"\b{key}\b\s*(?:=|:)\s*(" + _VAL + r")", re.IGNORECASE),
    # name is value / name of value / name to value
    re.compile(r"\b{key}\b\s+(?:is|are|of|to|as)\s+(" + _VAL + r")", re.IGNORECASE),
    re.compile(r"\bthe\s+{key}\s+(" + _VAL + r")", re.IGNORECASE),
    re.compile(r"\bwith\s+(?:a\s+|an\s+|the\s+)?{key}\s+(?:of\s+)?(" + _VAL + r")", re.IGNORECASE),
]

_STOP_WORDS = {"and", "with", "the", "a", "an", "for", "to", "of", "in", "on", "at", "using"}


def _speak_value(v: Any) -> str:
    """Write a value the way the adapter can read it back.

    Scalars go in bare — that is what makes the prose arm prose. Containers go
    in as compact JSON, because there is no unambiguous English rendering of a
    nested object and inventing one would make the prose arm fail for a reason
    that has nothing to do with prose.
    """
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _clean_value(raw: str) -> str:
    """Trim a captured value without damaging what is inside it.

    Only a *trailing* period is dropped, and only when it looks like sentence
    punctuation rather than part of the value — `11.5` and `report.md` must
    survive intact.
    """
    v = raw.strip()
    # A remark in parentheses after the value is commentary, not value:
    # `false (defaulting to false as not specified)` is `false`. A value that
    # is nothing but such a remark, `(not specified, so the default is used)`
    # or `(you need to provide the meter id)`, is no value at all and the
    # argument is left unset.
    v = re.sub(r"\s*\([^()]*\)\s*$", "", v).strip()
    if not v or v.startswith("("):
        return ""
    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
        return v[1:-1]
    v = re.split(r"\s+(?:and|then|while|but)\s+", v)[0].strip()
    v = v.rstrip(",;:")
    # A trailing period is always sentence punctuation: no value ends with a
    # bare dot. Interior dots (11.5, report.md, E-1207) are left alone.
    while len(v) > 1 and v.endswith("."):
        v = v[:-1].rstrip()
    return v.strip()


def _coerce_to(value: Any, param: ParamIR) -> Any:
    kind = param.type.kind
    if isinstance(value, (dict, list)):
        return coerce_text_value(value, param.type)
    v = str(value).strip()
    if kind == TypeKind.ENUM:
        for member in param.type.enum_values:
            if str(member).lower() == v.lower():
                return member
        for member in param.type.enum_values:
            if str(member).lower() in v.lower():
                return member
        return v
    if kind in (TypeKind.INTEGER, TypeKind.NUMBER):
        m = re.search(r"[-+]?\d+(?:\.\d+)?", v.replace(",", ""))
        if m:
            f = float(m.group(0))
            return int(f) if kind == TypeKind.INTEGER and f.is_integer() else f
        return v
    if kind == TypeKind.BOOLEAN:
        return v.lower() in ("true", "yes", "on", "enabled", "1")
    if kind == TypeKind.ARRAY:
        parsed = try_json(v)
        if isinstance(parsed, list):
            return parsed
        return [s.strip() for s in re.split(r",| and ", v) if s.strip()]
    if kind == TypeKind.OBJECT:
        # Not strict JSON only: a nested object written any other way
        # (`{format: md}`, `queue: billing, summary: ...`, an indented block)
        # would otherwise come back as {"_raw": ...} and be graded as an unknown
        # argument. Read it against the object's fields.
        return coerce_text_value(v, param.type)
    return v


def _balanced_from(text: str, start: int) -> str | None:
    """The balanced {...} or [...] span beginning at ``start``."""
    opener = text[start]
    closer = {"{": "}", "[": "]"}.get(opener)
    if closer is None:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _find_tool(text: str, universe: ToolUniverse) -> ToolIR | None:
    """Pick the tool the prose is talking about.

    Exact name mention wins, and among mentioned names the *longest* wins.
    Universes routinely hold a tool and its variants — ``documents_upload``
    alongside ``documents_upload_v1`` — and one name is a prefix of the other,
    so first-match returns the base tool for a response that clearly named the
    variant. Since variants are how tool count is scaled, that misattribution
    grows with the tool count and would have been read as prose degrading with
    tool count, which is exactly what RQ3 measures.
    """
    low = text.lower()
    mentioned = [t for t in universe if t.name.lower() in low]
    if mentioned:
        return max(mentioned, key=lambda t: len(t.name))
    if os.environ.get("TOOLFORM_NL_STRICT_TOOL"):
        # The strictness-matched reading: the tool must be
        # named literally; the word-overlap fallback below is what makes the prose
        # parser's strict and lenient rates differ by 0.01% where every other
        # protocol's differ by 3 to 11%.
        return None
    best, best_score = None, 0.0
    for t in universe:
        words = [w for w in t.name.lower().split("_") if w not in _STOP_WORDS]
        if not words:
            continue
        hits = sum(1 for w in words if w in low)
        score = hits / len(words)
        pnames = [p.name for p in t.params]
        if pnames:
            score += 0.4 * sum(1 for p in pnames if p.lower() in low) / len(pnames)
        if score > best_score:
            best, best_score = t, score
    return best if best_score >= 0.5 else None


def parse_intent(text: str, universe: ToolUniverse) -> tuple[list[ToolCall], str]:
    """Rule-based prose -> calls. Returns (calls, note describing what fired)."""
    body = strip_reasoning(text)

    # A prose answer that happens to contain JSON is still a JSON answer.
    obj = try_json(strip_fences(body))
    if obj is not None:
        calls = calls_from_json(obj)
        if calls:
            return calls, "embedded-json"

    segments = _split_intents(body, universe)
    calls: list[ToolCall] = []
    notes: list[str] = []
    for seg in segments:
        tool = _find_tool(seg, universe)
        if tool is None:
            continue
        args: dict[str, Any] = {}
        # A `name: value` list, one per line (bulleted or not, indented blocks
        # for nested objects), is what models actually write when told to give
        # `name: value`. Read it first; the sentence patterns below fill what
        # the list did not cover.
        listed = _kv_lines(seg, tool)
        # Pass one: only values with a key naming them.
        claimed: list[str] = []
        pending_enums: list[ParamIR] = []
        for p in tool.params:
            if p.name in listed:
                if listed[p.name] is None:
                    continue  # named with no value: not an argument, not guessed
                args[p.name] = listed[p.name]
                if isinstance(listed[p.name], str):
                    claimed.append(listed[p.name])
                continue
            val = _extract_param(seg, p, allow_bare_enum=False)
            if val is not None:
                args[p.name] = _coerce_to(val, p)
                if isinstance(val, str):
                    claimed.append(val)
            elif p.type.kind == TypeKind.ENUM:
                pending_enums.append(p)
        # A nested field written flat, in a layout the line reader does not
        # see (`tool: k=v, k=v` on one line, `value: k: v`): the sentence
        # patterns read it as they read a top-level parameter, and
        # recover_structure moves it into its object.
        # A parenthetical that says "(default: cabin: economy)" names what the
        # model is *not* setting; the pairs inside it are not arguments.
        seg_pairs = _DEFAULT_PAREN.sub(" ", seg)
        for p in tool.params:
            if p.name in args:
                continue
            for f in getattr(p.type, "fields", ()) or ():
                if f.name in listed or f.name in args or tool.param(f.name) is not None:
                    continue
                val = _explicit_value(seg_pairs, f)
                if val is not None:
                    listed[f.name] = _coerce_to(val, f)
                    if isinstance(val, str):
                        claimed.append(val)
        # Fields the model wrote flat that belong inside a nested object.
        for k, v in listed.items():
            if k not in args and v is not None and tool.param(k) is None:
                args[k] = v
        # Pass two: bare enum members, but only in text no other argument owns.
        if pending_enums:
            leftover = seg
            for val in claimed:
                leftover = leftover.replace(val, " ")
            for p in pending_enums:
                val = _extract_param(leftover, p)
                if val is not None:
                    args[p.name] = _coerce_to(val, p)
        # a single unnamed quoted string can fill a lone required argument
        req_missing = [p for p in tool.params if p.required and p.name not in args]
        if len(req_missing) == 1:
            quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', seg)
            flat = [a or b for a, b in quoted]
            if len(flat) == 1:
                args[req_missing[0].name] = _coerce_to(flat[0], req_missing[0])
                notes.append("single-quoted-fill")
        # A sentence that names a tool only to say it does not fit ("No tool
        # can merge two bookings", "the devops_deploy_v2 tool only allows
        # ...") is a refusal, not a call, when it gives the tool no argument
        # and the tool takes at least one.
        if (
            _REFUSAL.search(seg)
            and any(q.required for q in tool.params)
            and not _assigns_any(seg, tool)
            and not _QUOTED.search(seg)
        ):
            notes.append("refusal")
            continue
        moved: list[str] = []
        args = recover_structure(args, tool, moved)
        if moved:
            notes.append("renested")
        calls.append(ToolCall(name=tool.name, arguments=args))
        notes.append("rule-based")
    return calls, ",".join(sorted(set(notes))) or "no-match"


# A key is an identifier, or up to four words (a spaced name, or a question
# such as "What is the shared with?"). A whole sentence before a colon is not
# a key: "I will use get_weather with city: Paris" must not be read as one.
_REFUSAL = re.compile(
    r"\b(?:no tool|none of the (?:available |listed )?tools|cannot|can't|can not|unable to|"
    r"not (?:able|possible|supported|available)|does not support|do not support|don't (?:have|support)|"
    r"isn't (?:a|any) tool|is no tool)\b",
    re.IGNORECASE,
)
# A wrapper word a model puts before each pair (`value: city: Paris`,
# `name: city: Paris`) when told to answer as `name: value`.
_WRAPPER_KEYS = {"value", "name", "param", "parameter", "argument", "arg", "field", "key"}
_KV_LINE = re.compile(
    r"^(\s*)(?:[-*\u2022]\s+)?[`<\"'*]*([A-Za-z_][\w.\-]*(?:[ ][A-Za-z_][\w.\-?]*){0,3}\??)[`>\"'*]*\s*[:=]\s*(.*)$"
)
_SKIP_KEYS = {
    "tool",
    "tools",
    "function",
    "parameters",
    "arguments",
    "values",
    "here are the values",
    "here are the parameters",
    "note",
    "answer",
    "action",
}


_DEFAULT_PAREN = re.compile(r"\((?:defaults?|optional|omitted|not (?:given|provided|set))\b[^)]*\)", re.IGNORECASE)
_QUOTED = re.compile(r"[\"'][^\"'\n]{1,160}[\"']")
_NO_VALUE = {
    "",
    "not provided",
    "not given",
    "not specified",
    "none",
    "n/a",
    "null",
    "optional",
    "default",
    "unknown",
    "not applicable",
    "omitted",
    "not needed",
}


def _explicit_value(seg: str, p: ParamIR) -> str | None:
    """A nested field's value, but only from an explicit `name: value` or
    `name = value` (any spelling the schema may have shown). The looser
    sentence patterns read "the user provided `source`" as a value for a
    field called `user`; a nested field written flat is written as a pair,
    so a pair is all this accepts. A pair whose value is a placeholder
    ("not provided") is the model naming the field, not giving it."""
    for key in name_variants(p.name):
        # `[ \t]*` after the separator: `\s*` would run over a line break and
        # read the next line's key as this field's value (`quantity:` with
        # nothing after it, then `gift_wrap:`).
        m = re.search(
            rf"(?<![\w.-]){re.escape(key)}[ \t]*[:=][ \t]*(\"[^\"\n]*\"|'[^'\n]*'|[^,;\n]+)", seg, re.IGNORECASE
        )
        if m:
            val = _clean_value(m.group(1))
            if val.lower().strip("().") in _NO_VALUE:
                return None
            return val
    return None


def _assigns_any(seg: str, tool: ToolIR) -> bool:
    """Does the text give any declared parameter a value explicitly (`key: v`,
    `key = v`)? The sentence patterns can read "version of a service" as a
    value; an explicit assignment is what separates a call from a sentence
    that only mentions the tool."""
    names = [v for p in tool.params for v in name_variants(p.name)]
    names += [v for p in tool.params for f in (getattr(p.type, "fields", ()) or ()) for v in name_variants(f.name)]
    return any(re.search(rf"(?<![\w.-]){re.escape(k)}\s*[:=]", seg, re.IGNORECASE) for k in names)


def _kv_lines(seg: str, tool: ToolIR) -> dict[str, Any]:
    """Read `name: value` lines, with indented blocks as nested objects.

    Returns values keyed by the schema's parameter name where the key
    resolves, and by the model's own key where it does not, so the caller
    can re-nest a flat field. Lines whose key resolves to nothing the tool
    declares (top level or nested) are ignored: prose is full of colons.
    """
    lines = seg.splitlines()
    out: dict[str, Any] = {}
    nested_names = {}
    for p in tool.params:
        for f in getattr(p.type, "fields", ()) or ():
            nested_names.setdefault(canonical_name(f.name), f)
    # Several pairs on one line (`city: Paris, unit: F`): a scalar value ends
    # where the next declared name begins.
    # The tool's own name and the wrapper words end a value too:
    # `tool: title: X; tool: borrower: Y` on one line.
    known = sorted(
        {v for p in tool.params for v in name_variants(p.name)}
        | {v for f in nested_names.values() for v in name_variants(f.name)}
        | set(name_variants(tool.name))
        | _WRAPPER_KEYS,
        key=len,
        reverse=True,
    )
    next_key = (
        re.compile(r"[,;]?\s+(?:and\s+)?(?:" + "|".join(re.escape(k) for k in known) + r")\s*[:=]", re.IGNORECASE)
        if known
        else None
    )
    i = 0
    while i < len(lines):
        m = _KV_LINE.match(lines[i])
        if not m:
            i += 1
            continue
        indent, key, rest = len(m.group(1)), m.group(2).strip(), m.group(3)
        j = i + 1
        block: list[str] = []
        while j < len(lines):
            nxt = lines[j]
            if not nxt.strip():
                j += 1
                continue
            if len(nxt) - len(nxt.lstrip()) <= indent:
                break
            block.append(nxt)
            j += 1
        p = tool.param(key)
        if p is None and key.endswith("?"):
            p = loose_param(tool, key)
        f = nested_names.get(canonical_name(key))
        if (
            p is None
            and f is None
            and not block
            and rest.strip()
            and _KV_LINE.match(rest)
            and (canonical_name(key) == canonical_name(tool.name) or key.lower() in _WRAPPER_KEYS)
        ):
            # `devops_deploy_v2: service=auth-api, replicas=20` or
            # `value: site: office`: the pair is what follows the wrapper.
            lines[i] = rest
            continue
        if p is None and f is None:
            i = j if block else i + 1
            continue
        if p is None and key.lower().rstrip(":") in _SKIP_KEYS:
            # a filler word ("note", "values") that happens to match a nested
            # field name is prose, not an argument; a declared parameter
            # called `action` is an argument
            i = j if block else i + 1
            continue
        if rest.strip() and rest.strip()[0] in "{[":
            span = _balanced_from(rest, rest.index(rest.strip()[0]))
            raw: Any = span if span else rest
        elif block and not rest.strip():
            raw = "\n".join(block)
        elif block:
            raw = rest + "\n" + "\n".join(block)
        else:
            # A scalar ends where the next declared name begins; so does a
            # list written inline (`to: a@x.com, cc: b@x.com, subject: ...`),
            # whose items are the commas before that name.
            scalar = p is not None and p.type.kind != TypeKind.OBJECT
            if scalar and next_key is not None:
                m2 = next_key.search(rest)
                if m2:
                    rest = rest[: m2.start()]
            raw = _clean_value(rest)
            if not raw:
                # `title:` with nothing after it, or only a parenthetical
                # remark: the model named the argument and gave it no value.
                # Mark it so the caller neither passes it nor fills it from
                # the prose below (the sentence patterns cross line ends and
                # read the next line as the value).
                if p is not None:
                    out[p.name] = None
                i = j if block else i + 1
                continue
        if p is not None:
            out[p.name] = _coerce_to(raw, p)
        else:
            out[key] = coerce_text_value(raw, f.type)
        i = j if block else i + 1
    return out


def _split_intents(text: str, universe: ToolUniverse | None = None) -> list[str]:
    """Split prose into one segment per intended call.

    A numbered or bulleted item starts a new segment only if it names a tool.
    Models write their arguments as a bulleted list under one sentence, and
    splitting on every bullet used to leave the tool in one segment and every
    argument in others, where no tool was found and they were dropped.
    """
    parts = re.split(r"\n\s*(?:\d+[.)]\s*|[-*\u2022]\s+)", text)
    parts = [p for p in parts if p.strip()]
    if len(parts) > 1:
        if universe is None:
            return parts
        names = [t.name.lower() for t in universe]
        merged: list[str] = []
        for part in parts:
            # The last bullet of a list carries whatever the model wrote after
            # it ("The other parameters are optional..."), separated by a
            # blank line. Judge the part by its argument lines, up to that
            # blank line; the closing prose is its own part, so the last listed
            # argument is not lost when the whole part fails the line pattern.
            head, _, tail = part.strip().partition("\n\n")
            low = head.lower()
            mentions = any(n in low for n in names)
            # An argument line (`- queue: billing`) belongs to the intent
            # above it. Other prose that names no tool stays its own segment
            # and is ignored downstream, as it always was: gluing it onto the
            # intent would let a rambling continuation supply arguments.
            if merged and not mentions and _KV_LINE.match(head.splitlines()[0]):
                merged[-1] = merged[-1] + "\n" + head
                # The closing prose is a segment only when it names a tool
                # outright. "This will book your travel as requested" scores
                # as travel_book_v1 on the loose word match and became an
                # empty second call; prose naming no tool is dropped.
                if tail.strip() and any(n in tail.lower() for n in names):
                    merged.append(tail)
            else:
                merged.append(part)
        return merged
    # "call X ... then call Y ..."
    parts = re.split(r"(?i)\b(?:then|after that|next|and then)\b", text)
    return [p for p in parts if p.strip()] or [text]


def _extract_param(text: str, p: ParamIR, *, allow_bare_enum: bool = True) -> str | None:
    """Pull one parameter's value out of prose.

    ``allow_bare_enum`` controls the last-resort rule that accepts an enum
    member appearing on its own, with no key naming it. That rule is needed —
    people do write "cancel the meeting" rather than "status: cancelled" — but
    it fires on any occurrence, including one inside another argument's value.
    A ``folder`` enum containing ``legal`` was being filled from the path
    ``/legal/nda.pdf``, inventing an argument the model never gave. The caller
    therefore runs it in a second pass, over text with the already-claimed
    values removed.
    """
    # Every spelling the schema may have shown: a recased rendering (Go,
    # Swift, the identifier-case ablation) makes the model write `startHour`,
    # and a key it was shown is not a mistake.
    keys = name_variants(p.name)

    # A container value is written as compact JSON. Splitting that on commas
    # would truncate it, so pull the whole balanced span first.
    if p.type.kind in (TypeKind.OBJECT, TypeKind.ARRAY):
        for key in keys:
            m = re.search(rf"(?<![\w.-]){re.escape(key)}\b\s*[:=]\s*([\[{{])", text, re.IGNORECASE)
            if not m:
                continue
            span = _balanced_from(text, m.start(1))
            if span:
                return span
        if p.type.kind == TypeKind.OBJECT:
            # `details: queue billing, summary Double charged` runs to the end
            # of its line; the fields are read against the schema later.
            for key in keys:
                m = re.search(rf"(?<![\w.-]){re.escape(key)}\b\s*[:=]\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
                if m and m.group(1).strip():
                    return m.group(1).strip()

    for key in keys:
        esc = re.escape(key)
        for tmpl in _ASSIGN_PATTERNS:
            pat = re.compile(tmpl.pattern.replace("{key}", esc), tmpl.flags)
            m = pat.search(text)
            if m:
                val = _clean_value(m.group(1))
                if val and val.lower() not in ("the", "a", "an", "it"):
                    return val
    # enums can be matched by their literal members appearing in the prose
    if allow_bare_enum and p.type.kind == TypeKind.ENUM:
        for member in p.type.enum_values:
            if re.search(rf"\b{re.escape(str(member))}\b", text, re.IGNORECASE):
                return str(member)
    return None


@register_protocol
class NLIntentProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="nl_intent",
        name="Natural-language intent",
        description="The model says in words which tool it will use and with "
        "what values; a schema-guided rule adapter converts that to a call.",
        real_world_origin="Natural Language Tools (NLT)",
        structured=False,
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return (
            "Answer in plain English. Name the tool you would use and give a "
            "value for each piece of information it needs, written as "
            "`name: value`. Do not write JSON or code. If no tool fits, say so "
            "in one sentence."
        )

    def example(self, call: ToolCall) -> str:
        bits = ", ".join(f"{k}: {_speak_value(v)}" for k, v in call.arguments.items())
        return f"I will use {call.name} with {bits}."

    def render_calls(self, calls) -> str:
        """Number several intents so the splitter can tell them apart.

        Prose has no delimiter. A numbered list is the least artificial thing a
        person writing several intents would actually do, and `_split_intents`
        already recognises it.
        """
        calls = list(calls)
        if len(calls) <= 1:
            return "\n".join(self.example(c) for c in calls)
        return "\n".join(f"{i}. {self.example(c)}" for i, c in enumerate(calls, 1))

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        calls, note = parse_intent(text, universe)
        if not calls and declares_no_call(text):
            return ParseResult(calls=[], ok=True, mode="strict", matched_syntax=self.meta.id, note="explicit-no-call")
        return ParseResult(
            calls=calls,
            ok=bool(calls),
            mode="strict",
            matched_syntax=self.meta.id if calls else "",
            note=note,
            n_candidates=len(_split_intents(text, universe)),
        )


@register_protocol
class NLStructuredIntentProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="nl_intent_structured",
        name="Natural-language intent with a fixed sentence frame",
        description="Natural language constrained to the frame 'Use TOOL with "
        "arg = value, arg = value.' Keeps the natural-language channel while removing "
        "most of the parsing ambiguity.",
        novel=True,
        structured=False,
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return (
            "Answer with exactly one sentence in this frame and nothing else:\n"
            "Use <tool name> with <arg> = <value>, <arg> = <value>.\n"
            "If no tool fits, answer exactly: No tool is needed."
        )

    def example(self, call: ToolCall) -> str:
        bits = ", ".join(f"{k} = {_speak_value(v)}" for k, v in call.arguments.items())
        return f"Use {call.name} with {bits}."

    _FRAME = re.compile(r"use\s+([A-Za-z_][\w.]*)\s+with\s+(.*)", re.IGNORECASE | re.DOTALL)
    _KV = re.compile(r"([A-Za-z_]\w*)\s*=\s*(\"[^\"]*\"|'[^']*'|\[[^\]]*\]|\{[^}]*\}|[^,\n]+)")

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        body = strip_reasoning(text)
        calls: list[ToolCall] = []
        renested = False
        for m in self._FRAME.finditer(body):
            name = m.group(1).strip(".,`'\" ")
            tool = universe.get(name)
            if tool is None:
                continue
            args: dict[str, Any] = {}
            for k, raw in self._KV.findall(m.group(2)):
                spec = tool.param(k)
                if spec is not None:
                    args[spec.name] = _coerce_to(_clean_value(raw), spec)
                else:
                    args[k] = _clean_value(raw)
            moved: list[str] = []
            calls.append(ToolCall(name=tool.name, arguments=recover_structure(args, tool, moved)))
            if moved:
                renested = True
        if not calls:
            fallback, note = parse_intent(body, universe)
            if fallback:
                return ParseResult(
                    calls=fallback, ok=True, mode="strict", matched_syntax="nl_intent", note="frame-miss:" + note
                )
        if not calls and declares_no_call(body):
            return ParseResult(calls=[], ok=True, mode="strict", matched_syntax=self.meta.id, note="explicit-no-call")
        return ParseResult(
            calls=calls,
            ok=bool(calls),
            mode="strict",
            matched_syntax=self.meta.id if calls else "",
            note="renested" if renested else "",
        )


@register_protocol
class KeyValueCallProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="key_value_call",
        name="Key-value block",
        description="`TOOL: name` then one `arg: value` line each. Structured "
        "but with no brackets or quoting to get wrong.",
        real_world_origin="Header-style key/value blocks",
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return "Answer with a key-value block and nothing else:\nTOOL: <tool name>\n<arg>: <value>\n<arg>: <value>"

    def example(self, call: ToolCall) -> str:
        lines = [f"TOOL: {call.name}"]
        for k, v in call.arguments.items():
            val = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
            lines.append(f"{k}: {val}")
        return "\n".join(lines)

    _TOOL_LINE = re.compile(r"^\s*(?:TOOL|tool|Tool)\s*:\s*(.+?)\s*$", re.MULTILINE)

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        body = strip_fences(strip_reasoning(text))
        blocks: list[tuple[str, str]] = []
        matches = list(self._TOOL_LINE.finditer(body))
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
            blocks.append((m.group(1).strip(), body[m.end() : end]))
        calls: list[ToolCall] = []
        moved: list[str] = []
        for name, rest in blocks:
            tool = universe.get(name)
            if tool is not None:
                # A nested object written as an indented block, an
                # inline literal or `k=v, k=v` was read line by line and lost.
                args = _kv_lines(rest, tool)
                args = recover_structure(args, tool, moved)
            else:
                args = {}
                for line in rest.splitlines():
                    if ":" not in line:
                        continue
                    k, v = line.split(":", 1)
                    args[k.strip().strip("-* ")] = _clean_value(v)
            calls.append(ToolCall(name=tool.name if tool else name, arguments=args))
        return ParseResult(
            calls=calls,
            ok=bool(calls),
            mode="strict",
            matched_syntax=self.meta.id if calls else "",
            n_candidates=len(blocks),
            note="renested" if moved else "",
        )


@register_protocol
class YAMLCallProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="yaml_call",
        name="YAML call block",
        description="The call as a small YAML document with name and arguments keys.",
        real_world_origin="YAML-based agent output formats",
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return "Answer with YAML and nothing else:\nname: <tool name>\narguments:\n  <arg>: <value>"

    def example(self, call: ToolCall) -> str:
        lines = [f"name: {call.name}", "arguments:"]
        for k, v in call.arguments.items():
            val = v if isinstance(v, (int, float, bool)) else json.dumps(v, ensure_ascii=False)
            lines.append(f"  {k}: {val}")
        return "\n".join(lines)

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        body = strip_fences(strip_reasoning(text))
        obj = None
        try:
            import yaml  # type: ignore

            obj = yaml.safe_load(body)
        except Exception:  # noqa: BLE001
            obj = None
        if obj is None:
            obj = try_json(body)
        calls = calls_from_json(obj) if obj is not None else []
        if not calls:
            # fall back to the key-value reader, which handles flat YAML fine
            return get_kv_fallback(body, universe, self.meta.id)
        return ParseResult(calls=calls, ok=True, mode="strict", matched_syntax=self.meta.id, n_candidates=1)


def get_kv_fallback(body: str, universe: ToolUniverse, pid: str) -> ParseResult:
    m = re.search(r"^\s*name\s*:\s*(.+?)\s*$", body, re.MULTILINE)
    if not m:
        return ParseResult(calls=[], ok=False, mode="strict")
    tool = universe.get(m.group(1).strip())
    args: dict[str, Any] = {}
    if tool is None:
        return ParseResult(calls=[], ok=False, mode="strict")
    moved: list[str] = []
    args = recover_structure(_kv_lines(body[m.end() :], tool), tool, moved)
    return ParseResult(
        calls=[ToolCall(tool.name, args)],
        ok=True,
        mode="strict",
        matched_syntax=pid,
        note="kv-fallback,renested" if moved else "kv-fallback",
    )


@register_protocol
class TOMLCallProtocol(CallProtocol):
    meta = ProtocolMeta(
        id="toml_call",
        name="TOML call block",
        description="`[[call]]` array-of-tables with a name and an [call.arguments] table.",
        real_world_origin="TOML",
    )

    def instructions(self, universe: ToolUniverse) -> str:
        return (
            "Answer with TOML and nothing else. Repeat the block for each "
            "call:\n"
            '[[call]]\nname = "<tool name>"\n\n[call.arguments]\n<arg> = <value>'
        )

    def example(self, call: ToolCall) -> str:
        lines = ["[[call]]", f'name = "{call.name}"', "", "[call.arguments]"]
        for k, v in call.arguments.items():
            lines.append(f"{k} = {json.dumps(v, ensure_ascii=False)}")
        return "\n".join(lines)

    def render_calls(self, calls) -> str:
        """Several calls are several `[[call]]` entries.

        TOML has no way to repeat a plain `[call]` table, so joining single-call
        examples produced a document whose second block was unreachable: the
        parser saw one name, merged every block's arguments into it, and every
        parallel cell in the TOML arm was capped at one call with the wrong
        arguments. An array-of-tables is the idiomatic form and reads back.
        """
        return "\n\n".join(self.example(c) for c in calls)

    # A header line starting a new call: `[[call]]` or a bare `[call]`.
    _CALL_HEADER = re.compile(r"^\s*\[\[?call\]\]?\s*$")

    def parse(self, text: str, universe: ToolUniverse) -> ParseResult:
        body = strip_fences(strip_reasoning(text))

        # Split into one segment per call before reading anything, so a second
        # block can never fold its arguments into the first.
        segments: list[list[str]] = []
        for line in body.splitlines():
            if self._CALL_HEADER.match(line):
                segments.append([])
            elif segments:
                segments[-1].append(line)
        if not segments:
            segments = [body.splitlines()]

        calls: list[ToolCall] = []
        for seg in segments:
            block = "\n".join(seg)
            m = re.search(r'name\s*=\s*"([^"]+)"', block)
            if not m:
                continue
            tool = universe.get(m.group(1))
            if tool is None:
                continue
            args: dict[str, Any] = {}
            in_args = False
            for line in seg:
                s = line.strip()
                if s.startswith("["):
                    in_args = "arguments" in s
                    continue
                if in_args and "=" in s:
                    k, v = s.split("=", 1)
                    k = k.strip()
                    spec = tool.param(k)
                    parsed = try_json(v.strip())
                    val = parsed if parsed is not None else _clean_value(v)
                    args[k] = _coerce_to(val, spec) if (spec and isinstance(val, str)) else val
            calls.append(ToolCall(tool.name, args))

        return ParseResult(
            calls=calls,
            ok=bool(calls),
            mode="strict",
            matched_syntax=self.meta.id if calls else "",
            n_candidates=len(segments),
        )
