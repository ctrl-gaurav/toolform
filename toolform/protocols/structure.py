"""Recovering argument structure from text-valued answers.

Five protocols carry argument values as text with no native nesting: prose
(``nl_intent``), key-value blocks, command lines, URL query strings and XML
``<parameter>`` elements. The schema says which arguments are objects, so a
parser can recover the structure a model expressed in the only ways text
allows: an inline ``{k: v}`` literal without quotes, a ``k: v, k: v`` or
``k=v`` list, an indented block, or the nested fields written flat beside the
top-level arguments.

Before this module every one of those shapes was graded as a wrong argument.
Every tier-3 task carries one nested object, so the whole prose and XML arm
sat near 0.2 at every model size while the same models scored 0.85 in JSON.
That was the parser, not the model.

Typed literal protocols (JSON, Python, GraphQL, s-expressions) keep their own
syntax and use only :func:`parse_relaxed_object`, because unquoted keys and
keyword keys are correct syntax in those languages rather than a slip. They
never re-nest: a model that flattened a nested object in JSON ignored the
schema, and that is a real error.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from ..ir import ParamIR, ToolIR, TypeIR, TypeKind
from ..ir.types import canonical_name
from .base import balanced_value_at, try_json

_NUM = re.compile(r"^[-+]?\d+(?:\.\d+)?$")
_WORD_LITERALS = {
    "true": True,
    "false": False,
    "null": None,
    "none": None,
    "True": True,
    "False": False,
    "None": None,
    "nil": None,
}


# --------------------------------------------------------------------------- #
# relaxed object literals
# --------------------------------------------------------------------------- #


class _Cursor:
    def __init__(self, text: str) -> None:
        self.s = text
        self.i = 0

    def peek(self) -> str:
        return self.s[self.i] if self.i < len(self.s) else ""

    def skip(self) -> None:
        while self.i < len(self.s) and self.s[self.i] in " \t\r\n,":
            self.i += 1


def parse_relaxed_object(text: str) -> dict | list | None:
    """Read a ``{...}`` or ``[...]`` literal the way a lenient reader would.

    Accepts JSON, but also unquoted keys (``{format: "md"}``), keyword keys
    (``{:queue "billing"}``), ``=`` and ``=>`` between key and value, single
    quotes, bare-word values (``{queue: billing}``), Python and JSON word
    literals, and trailing commas. Returns ``None`` when the text is not a
    bracketed literal at all.
    """
    s = text.strip()
    if not s or s[0] not in "{[":
        return None
    strict = try_json(s)
    if isinstance(strict, (dict, list)):
        return strict
    cur = _Cursor(s)
    try:
        val = _value(cur, top=True)
    except _Bad:
        return None
    return val if isinstance(val, (dict, list)) else None


class _Bad(Exception):
    pass


def _value(cur: _Cursor, *, top: bool = False) -> Any:
    cur.skip()
    ch = cur.peek()
    if ch == "{":
        return _object(cur)
    if ch == "[":
        return _array(cur)
    if ch in ("'", '"'):
        return _quoted(cur)
    # bare token: up to a delimiter
    start = cur.i
    while cur.i < len(cur.s) and cur.s[cur.i] not in ",}]\n":
        cur.i += 1
    raw = cur.s[start : cur.i].strip()
    if not raw:
        raise _Bad
    if raw in _WORD_LITERALS:
        return _WORD_LITERALS[raw]
    if _NUM.match(raw):
        f = float(raw)
        return int(f) if f.is_integer() and "." not in raw else f
    return raw


def _quoted(cur: _Cursor) -> str:
    q = cur.peek()
    cur.i += 1
    out = []
    while cur.i < len(cur.s):
        ch = cur.s[cur.i]
        if ch == "\\" and cur.i + 1 < len(cur.s):
            out.append(cur.s[cur.i + 1])
            cur.i += 2
            continue
        if ch == q:
            cur.i += 1
            return "".join(out)
        out.append(ch)
        cur.i += 1
    raise _Bad


def _key(cur: _Cursor) -> str:
    cur.skip()
    ch = cur.peek()
    if ch in ("'", '"'):
        return _quoted(cur)
    if ch == ":":  # EDN keyword
        cur.i += 1
    start = cur.i
    while cur.i < len(cur.s) and (cur.s[cur.i].isalnum() or cur.s[cur.i] in "_.-?"):
        cur.i += 1
    key = cur.s[start : cur.i]
    if not key:
        raise _Bad
    return key


def _object(cur: _Cursor) -> dict:
    cur.i += 1  # {
    out: dict[str, Any] = {}
    while True:
        cur.skip()
        if cur.peek() == "}":
            cur.i += 1
            return out
        if not cur.peek():
            raise _Bad
        key = _key(cur)
        cur.skip()
        if cur.s.startswith("=>", cur.i):
            cur.i += 2
        elif cur.peek() in ":=":
            cur.i += 1
        out[key] = _value(cur)


def _array(cur: _Cursor) -> list:
    cur.i += 1  # [
    out: list[Any] = []
    while True:
        cur.skip()
        if cur.peek() == "]":
            cur.i += 1
            return out
        if not cur.peek():
            raise _Bad
        out.append(_value(cur))


# --------------------------------------------------------------------------- #
# schema-guided reading of loose text
# --------------------------------------------------------------------------- #


def name_variants(name: str) -> list[str]:
    """The spellings a model may use for one identifier."""
    words = [w for w in re.split(r"[_\-\s]+", name) if w]
    if not words:
        return [name]
    low = [w.lower() for w in words]
    out = [
        name,
        " ".join(low),
        "-".join(low),
        "_".join(low),
        low[0] + "".join(w.capitalize() for w in low[1:]),
        "".join(w.capitalize() for w in low),
        "_".join(w.upper() for w in low),
    ]
    seen: set[str] = set()
    uniq = []
    for v in out:
        if v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq


def _fields_of(spec: TypeIR | None) -> tuple:
    return tuple(getattr(spec, "fields", ()) or ())


def extract_fields(text: str, fields: Iterable[Any]) -> dict[str, Any]:
    """Pull ``name value`` / ``name: value`` / ``name=value`` pairs for known fields.

    Schema-guided on purpose: only names the schema declares are looked for,
    so free prose cannot invent an argument. A value runs to the next comma,
    semicolon, newline or the next declared field name.
    """
    fields = list(fields)
    names = {}
    for f in fields:
        for v in name_variants(f.name):
            names[v.lower()] = f
    if not names:
        return {}
    alts = sorted(names, key=len, reverse=True)
    stop = r"(?=\s*(?:,|;|\n|$|\b(?:" + "|".join(re.escape(a) for a in alts) + r")\b\s*[:=]))"
    out: dict[str, Any] = {}
    for alt in alts:
        f = names[alt]
        if f.name in out:
            continue
        pat = re.compile(
            r"(?<![\w.-])" + re.escape(alt) + r"\s*(?:=>|[:=]|\s)\s*("
            r"\"[^\"]*\"|'[^']*'|[\[{]|.+?)" + stop,
            re.IGNORECASE | re.DOTALL,
        )
        m = pat.search(text)
        if not m:
            continue
        raw = m.group(1)
        if raw in ("{", "["):
            span = balanced_value_at(text, m.start(1))
            raw = span if span else raw
        out[f.name] = coerce_text_value(raw, f.type)
    return out


def coerce_text_value(value: Any, spec: TypeIR | None) -> Any:
    """Turn a text value into what the schema says it is, when that is unambiguous."""
    if spec is None:
        return value
    kind = spec.kind
    if isinstance(value, dict) and "_raw" in value and len(value) == 1:
        value = value["_raw"]
    if kind == TypeKind.OBJECT:
        if isinstance(value, dict):
            fields = _fields_of(spec)
            if not fields:
                return value
            by_canon = {canonical_name(f.name): f for f in fields}
            out = {}
            for k, v in value.items():
                f = by_canon.get(canonical_name(str(k)))
                out[f.name if f else k] = coerce_text_value(v, f.type) if f else v
            return out
        if isinstance(value, str):
            s = value.strip()
            if not s:
                return {}
            lit = parse_relaxed_object(s)
            if isinstance(lit, dict):
                return coerce_text_value(lit, spec)
            got = extract_fields(s, _fields_of(spec))
            return got if got else {"_raw": s}
        return value
    if kind == TypeKind.ARRAY:
        if isinstance(value, (list, tuple)):
            return [coerce_text_value(v, spec.item) for v in value]
        if isinstance(value, str):
            lit = parse_relaxed_object(value)
            if isinstance(lit, list):
                return lit
            s = value.strip().strip("\"'")
            return [x.strip().strip("\"'") for x in re.split(r",|\band\b", s) if x.strip()]
        return value
    if isinstance(value, str):
        s = value.strip()
        if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
            s = s[1:-1]
        if kind in (TypeKind.INTEGER, TypeKind.NUMBER):
            m = re.fullmatch(r"[-+]?\d+(?:\.\d+)?", s.replace(",", ""))
            if m:
                f = float(m.group(0))
                return int(f) if kind == TypeKind.INTEGER and f.is_integer() else f
            return s
        if kind == TypeKind.BOOLEAN:
            low = s.lower()
            if low in ("true", "yes", "on", "enabled", "1"):
                return True
            if low in ("false", "no", "off", "disabled", "0"):
                return False
            return s
        if kind == TypeKind.ENUM:
            for member in spec.enum_values or ():
                if str(member).lower() == s.lower():
                    return member
            return s
        return s
    return value


def recover_structure(args: dict[str, Any], tool: ToolIR | None, moved: list[str] | None = None) -> dict[str, Any]:
    """Make a flat, text-valued argument dict match the tool's shape.

    Two passes. First, a value given for an object-typed parameter as text
    (or as the ``{"_raw": ...}`` placeholder older parsers left) is read
    against that object's fields. Second, a key that is not a top-level
    parameter but is the name of exactly one nested field of exactly one
    object parameter is moved inside that object. A key that matches nothing,
    or more than one place, is left where it is and stays an unknown argument.

    Only text-valued protocols call this. Nothing here invents a value: every
    value moved or parsed was written by the model. A key that is moved is
    appended to ``moved`` when a list is given, so the parse can say that the
    structure was recovered rather than written; the grader reports
    ``call_exact_as_written`` beside ``call_exact`` from that flag.
    """
    if tool is None or not isinstance(args, dict):
        return args
    top = {canonical_name(p.name): p for p in tool.params}
    objects = [p for p in tool.params if p.type.kind == TypeKind.OBJECT and _fields_of(p.type)]
    out: dict[str, Any] = {}
    homeless: list[tuple[str, Any]] = []
    for k, v in args.items():
        p = top.get(canonical_name(str(k)))
        if p is None:
            homeless.append((k, v))
            continue
        out[p.name] = coerce_text_value(v, p.type)
    for k, v in homeless:
        ck = canonical_name(str(k))
        homes = [(p, f) for p in objects for f in _fields_of(p.type) if canonical_name(f.name) == ck]
        if len(homes) == 1:
            p, f = homes[0]
            moved_value = coerce_text_value(v, f.type)
            if not _fits(moved_value, f.type):
                # `a1: Denver` when a1 is an integer field: the model used a
                # wrong name, and moving it would only turn one error into
                # another. Leave it as the unknown argument it is.
                out[k] = v
                continue
            cur = out.get(p.name)
            if not isinstance(cur, dict) or ("_raw" in cur and len(cur) == 1):
                cur = {}
            if f.name not in cur:
                cur[f.name] = moved_value
                if moved is not None:
                    moved.append(str(k))
            elif cur[f.name] != moved_value:
                # The nested value and a flat duplicate disagree
                # (``{details: {city: Boston}, city: Paris}``). The flat key
                # stays where it is, an unknown argument that fails the call, and the conflict is
                # recorded so ``call_exact_as_written`` excludes the turn.
                out[k] = v
                if moved is not None:
                    moved.append(f"{k}!conflict")
            out[p.name] = cur
        else:
            out[k] = v
    return out


def _fits(value: Any, spec: TypeIR | None) -> bool:
    """Does a coerced value have the declared scalar kind? Containers pass."""
    if spec is None:
        return True
    kind = spec.kind
    if kind in (TypeKind.INTEGER, TypeKind.NUMBER):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == TypeKind.BOOLEAN:
        return isinstance(value, bool)
    if kind == TypeKind.ENUM:
        return value in (spec.enum_values or ()) or not spec.enum_values
    return True


def loose_param(tool: ToolIR | None, key: str) -> ParamIR | None:
    """A parameter whose spelled-out name appears inside a longer key.

    For renderings that phrase a parameter as a question ("What is the
    shared with?"). Whole-word, and unique: "id" alone matches nothing when
    the tool has both ``record_id`` and ``ticket_id``.
    """
    if tool is None:
        return None
    low = re.sub(r"[^a-z0-9 ]+", " ", key.lower())
    hits = []
    for p in tool.params:
        spaced = " ".join(w for w in re.split(r"[_\-\s]+", p.name.lower()) if w)
        if re.search(r"\b" + re.escape(spaced) + r"\b", low):
            hits.append(p)
    if len(hits) == 1:
        return hits[0]
    if hits:
        return max(hits, key=lambda p: len(p.name))
    return None


__all__ = [
    "coerce_text_value",
    "extract_fields",
    "loose_param",
    "name_variants",
    "parse_relaxed_object",
    "recover_structure",
]
