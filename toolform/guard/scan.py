"""Scan tool metadata for instructions hidden in the description channel.

Scanned: the tool description, ``returns_description``, every parameter
description at any depth, string enum values, string defaults and examples,
and string values in ``ToolIR.annotations`` (MCP annotations included). The
tool's name is checked only for role markup (TS106) and non-printing text
(TS109).
"""

from __future__ import annotations

import logging
import re
from bisect import bisect_left
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterator, Sequence

from ..ir import ParamIR, ToolIR, TypeIR, TypeKind
from ..ir.types import canonical_name
from .rules import (
    CALL_VERBS,
    ORDER_WORDS,
    OUTPUT_VERBS,
    PARAM_DESC_LIMIT,
    RULES_BY_ID,
    SENSITIVE_WORDS,
    SENTINEL,
    STRICTNESS,
    TOOL_DESC_LIMIT,
    TS101_ADDRESSED,
    TS101_NEGATIVE_ACT,
    TS101_OVERRIDE,
    TS101_POSITIVE_ACT,
    TS101_TAMPER,
    TS102,
    TS105_EXFIL,
    TS105_PATHS,
    TS105_PHRASES,
    TS105_SILENT,
    TS106_MARKUP,
    TS107_CAPS,
    TS107_PHRASES,
    TS109_CHARS,
    TS110_MIXED,
    URL_OR_EMAIL,
    fold_confusables,
    html_comments,
    split_sentences,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..sdk.toolset import Toolset

_SEV_ORDER = {"high": 0, "medium": 1, "low": 2}

log = logging.getLogger("toolform.guard")

#: Facts from the study shown beside every report; ids in the advisor's facts.json.
GUARD_FACT_IDS = (
    "injection_min",
    "injection_max",
    "injection_decoy_min",
    "injection_decoy_max",
    "trust_line_sentinel",
    "trust_line_valid",
    "hijack_schema_valid",
    "descriptions_off_min",
    "descriptions_off_max",
    "descriptions_off_python_stub",
)


@dataclass
class Finding:
    """One rule firing on one span of one field."""

    rule_id: str
    rule_name: str
    severity: str
    tool: str
    field: str
    text: str
    start: int
    end: int
    message: str

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable dict of every field."""
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "severity": self.severity,
            "tool": self.tool,
            "field": self.field,
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "message": self.message,
        }


@dataclass
class GuardReport:
    """The findings on a toolset and, after cleaning, what was removed."""

    strictness: str
    n_tools: int
    findings: list[Finding]
    flagged_tools: list[str]
    counts: dict[str, int]
    action: str = "report"
    removed: list[dict[str, Any]] = field(default_factory=list)
    toolset: "Toolset | None" = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    kept: list[dict[str, Any]] = field(default_factory=list)
    strip_at: str | None = None

    def max_severity(self) -> str | None:
        """The most severe finding's severity, or None when there is none."""
        if not self.findings:
            return None
        return min((f.severity for f in self.findings), key=lambda s: _SEV_ORDER.get(s, 9))

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable dict; ``tools`` holds the cleaned tools when a toolset is set."""
        d: dict[str, Any] = {
            "strictness": self.strictness,
            "n_tools": self.n_tools,
            "findings": [f.to_dict() for f in self.findings],
            "flagged_tools": list(self.flagged_tools),
            "counts": dict(self.counts),
            "max_severity": self.max_severity(),
            "action": self.action,
            "removed": [dict(r) for r in self.removed],
            "kept": [dict(k) for k in self.kept],
            "strip_at": self.strip_at,
            "evidence": [dict(e) for e in self.evidence],
            "summary": self.summary(),
        }
        if self.toolset is not None:
            d["tools"] = self.toolset.to_ir()["tools"]
        return d

    def summary(self) -> str:
        """One plain sentence about what was found and done."""
        if not self.findings:
            text = f"No findings in {self.n_tools} tools at {self.strictness} strictness."
        else:
            parts = ", ".join(
                f"{self.counts.get(s, 0)} {s}" for s in ("high", "medium", "low") if self.counts.get(s, 0)
            )
            n = len(self.findings)
            text = (
                f"{n} finding{'s' if n != 1 else ''} in {len(self.flagged_tools)} of {self.n_tools} "
                f"tools ({parts}) at {self.strictness} strictness."
            )
        if self.action == "strip":
            text += f" Stripped {len(self.removed)} span{'s' if len(self.removed) != 1 else ''}."
            if self.kept:
                n = len(self.kept)
                text += f" Kept {n} flagged span{'s' if n != 1 else ''} that stripping cannot remove (see kept)."
        elif self.action == "drop_descriptions":
            text += f" Removed {len(self.removed)} description field{'s' if len(self.removed) != 1 else ''}."
        return text


# --------------------------------------------------------------------------- #
# single rules
# --------------------------------------------------------------------------- #


def _canon_set(names: Sequence[str]) -> set[str]:
    return {canonical_name(n) for n in names if n}


def _is_single_word(name: str) -> bool:
    return not re.search(r"[_\-]|[a-z][A-Z]", name)


class CatalogueIndex:
    """The catalogue's names and parameters, prepared once for every field of every tool.

    A multi-word name (``get_user``, ``getUser``) is found by its canonical
    form among the sentence's words. A one-word name ("bash", "weather") is
    often an ordinary word, so it counts only when the text marks it as a
    name: in backticks, quotes or brackets, or followed by "tool" or
    "function". Both are dictionary lookups, so a scan does not grow with the
    size of the catalogue.
    """

    def __init__(self, catalogue_names: Sequence[str] = (), other_param_names: Sequence[str] = ()) -> None:
        self.names = [n for n in catalogue_names if n]
        self.order = {n: i for i, n in enumerate(self.names)}
        self.multi: dict[str, list[str]] = {}
        self.single: dict[str, list[str]] = {}
        for n in self.names:
            if _is_single_word(n):
                self.single.setdefault(n.lower(), []).append(n)
            else:
                self.multi.setdefault(canonical_name(n), []).append(n)
        self.canon_names = _canon_set(self.names)
        self.other_params = _canon_set(other_param_names)


_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]*")
_MARKED = re.compile(
    r"[`'\"(\[](?P<a>[^\s`'\"()\[\]]{1,64})[`'\")\]]|"
    r"(?<![^\s`'\"(\[])(?P<b>[^\s`'\"()\[\]]{1,64})(?=\s+(?:tool|function)\b)",
    re.I,
)
_VERB_WORD = re.compile(r"[A-Za-z']+")
_CALL_VERB_FULL = re.compile(CALL_VERBS, re.I)


def _name_hits(sentence: str, index: CatalogueIndex) -> dict[str, list[int]]:
    """Where each catalogue name occurs in a sentence: ``{name: [positions]}``."""
    hits: dict[str, list[int]] = {}
    if index.multi:
        for m in _WORD.finditer(sentence):
            for name in index.multi.get(canonical_name(m.group(0)), ()):
                hits.setdefault(name, []).append(m.start())
    if index.single:
        for m in _MARKED.finditer(sentence):
            word = m.group("a") if m.group("a") is not None else m.group("b")
            for name in index.single.get(word.lower(), ()):
                pos = m.start("a") - 1 if m.group("a") is not None else m.start("b")
                hits.setdefault(name, []).append(pos)
    return hits


def _called(positions: list[int], verbs: list[tuple[int, str]], starts: list[int]) -> bool:
    """A verb of calling within the six words before one of the positions (``starts``: where each word begins)."""
    for pos in positions:
        i = bisect_left(starts, pos)
        if any(_CALL_VERB_FULL.fullmatch(w) for _, w in verbs[max(0, i - 6) : i]):
            return True
    return False


def _calls_named_tool(sentence: str, name: str) -> bool:
    """A verb of calling within the six words before the name."""
    index = CatalogueIndex([name])
    positions = _name_hits(sentence, index).get(name, [])
    verbs = [(m.start(), m.group(0)) for m in _VERB_WORD.finditer(sentence)]
    return _called(positions, verbs, [p for p, _ in verbs])


def _prerequisite_of(sentence: str, tool: str) -> bool:
    """The sentence states what must happen before this tool is used ("call a before b", on b)."""
    own = [r"this (?:tool|function)"]
    if tool:
        own.append(re.escape(tool))
    rx = r"\bbefore\s+(?:(?:using|calling|invoking|running)\s+)?(?:the\s+)?(?:" + "|".join(own) + r")\b"
    return re.search(rx, sentence, re.I) is not None


# An identifier in quotes is a value ('left_click'), and one inside <|...|> is
# role markup (TS106); neither is taken for a parameter name.
_IDENT_SNAKE = re.compile(r"(?<![A-Za-z0-9_./@|'\"-])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![A-Za-z0-9_@|'\"-])")
_IDENT_CAMEL = re.compile(r"(?<![A-Za-z0-9_./@|'\"-])[a-z]+(?:[A-Z][a-z0-9]+)+(?![A-Za-z0-9_@|'\"-])")
_IDENT_TICK = re.compile(r"`([A-Za-z_][A-Za-z0-9_.\-]*)`")
_URLISH = re.compile(URL_OR_EMAIL)
_QUOTED = re.compile(r"'[^'\s][^']{0,80}'|\"[^\"\s][^\"]{0,80}\"|`[^`\s][^`]{0,80}`")
_SENTINEL_WORD = re.compile(
    r"(?<![A-Za-z0-9_\-])(?=[A-Z0-9_\-]*\d)(?=[A-Z0-9_\-]*[A-Z])[A-Z0-9_\-]{4,}"
    r"(?![A-Za-z0-9_\-])"
)


def _unknown_identifiers(sentence: str, known: set[str]) -> list[str]:
    url_spans = [m.span() for m in _URLISH.finditer(sentence)]

    def in_url(i: int) -> bool:
        return any(a <= i < b for a, b in url_spans)

    found: list[str] = []
    for rx in (_IDENT_TICK, _IDENT_SNAKE, _IDENT_CAMEL):
        for m in rx.finditer(sentence):
            if in_url(m.start()):
                continue
            ident = m.group(1) if rx is _IDENT_TICK else m.group(0)
            parts = [p for p in re.split(r"[.]", ident) if p]
            if not parts:
                continue
            if any(canonical_name(p) in known for p in parts):
                continue
            if ident.lower() in ("true", "false", "null", "none"):
                continue
            if ident not in found:
                found.append(ident)
    return found


def _literal_value(value: str) -> bool:
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"`":
        return True
    if re.fullmatch(r"-?\d+(?:\.\d+)?", v) or v.lower() in ("true", "false", "null", "none"):
        return True
    if re.fullmatch(r"[A-Z][A-Z0-9_\-]{2,}", v) or _URLISH.fullmatch(v):
        return True
    return False


def _has_literal(sentence: str) -> bool:
    """A quoted value, a code such as OVERRIDE-7731, or an address."""
    return bool(_QUOTED.search(sentence) or _SENTINEL_WORD.search(sentence) or _URLISH.search(sentence))


_TS101_HIGH = (
    "An instruction addressed to the model, with a target: it tells the model what to call, set, say "
    "or reveal. In the study, models followed one such planted sentence on 38.48 to 54.16% of turns in "
    "every format that shows descriptions."
)
_TS101_MEDIUM = (
    "An imperative with no value, tool or reply as its target. Often ordinary usage guidance; read it "
    "to be sure it asks nothing beyond what the tool needs."
)
_TS101_LOW = (
    'A restriction on how to use the tool ("do not", "never"). Usually documentation; shown at strict strictness only.'
)


def scan_text(
    text: str,
    *,
    tool: str = "",
    field: str = "description",
    catalogue_names: Sequence[str] = (),
    param_names: Sequence[str] = (),
    other_param_names: Sequence[str] = (),
    known_words: Sequence[str] = (),
    index: CatalogueIndex | None = None,
) -> list[Finding]:
    """Every finding on one field's text, at every severity.

    ``catalogue_names`` are the names of every tool in the catalogue (TS103,
    TS104), ``param_names`` this tool's parameter names at any depth (TS102,
    TS104). ``other_param_names`` adds other tools' parameter names for TS102,
    and ``known_words`` more identifiers TS104 accepts (this tool's enum
    values, say). ``index`` is the catalogue prepared once by
    :class:`CatalogueIndex`; scanning a whole toolset passes it, so the work per
    field does not grow with the catalogue.
    """
    if not text:
        return []
    out: list[Finding] = []
    original = text
    text = fold_confusables(original)

    def add(rule_id: str, start: int, end: int, message: str, severity: str | None = None) -> None:
        rule = RULES_BY_ID[rule_id]
        out.append(
            Finding(
                rule_id=rule_id,
                rule_name=rule.name,
                severity=severity or rule.severity,
                tool=tool,
                field=field,
                text=original[start:end],
                start=start,
                end=end,
                message=message,
            )
        )

    sentences = split_sentences(text)

    def sentence_at(pos: int) -> tuple[int, int]:
        for s, e, _ in sentences:
            if s <= pos < e:
                return s, e
        return pos, pos + 1

    # TS109, TS110 and TS106 apply to every field, the name included.
    for m in re.finditer(TS109_CHARS, text):
        add(
            "TS109",
            m.start(),
            m.end(),
            f"An invisible control character (U+{ord(m.group(0)):04X}). "
            "A reader does not see it, but it can hide or reorder text.",
        )
    for a, b in html_comments(text):
        add("TS109", a, b, "An HTML comment: text a person reading a rendered page does not see.")
    if text != original:
        for m in re.finditer(TS110_MIXED, original):
            add(
                "TS110",
                m.start(),
                m.end(),
                f"The word {m.group(0)!r} mixes Latin letters with Cyrillic or Greek "
                "ones that look the same. The guard read it with those letters folded to Latin.",
            )
    marked: set[tuple[int, int]] = set()
    for m in re.finditer(TS106_MARKUP, text):
        s, e = sentence_at(m.start())
        if (s, e) in marked:
            continue
        marked.add((s, e))
        add(
            "TS106",
            s,
            e,
            f"Chat-template or role markup ({m.group(0).strip()!r}) inside tool metadata. "
            "It can make the text read as a message from the system or the assistant.",
        )
    if field == "name":
        return _ordered(out)

    idx = index if index is not None else CatalogueIndex(catalogue_names, other_param_names)
    params = _canon_set(param_names)
    all_params = params | idx.other_params
    known = params | idx.canon_names | _canon_set([tool]) | _canon_set(known_words)

    for s, e, sent in sentences:
        hits = _name_hits(sent, idx)
        verbs = [(m.start(), m.group(0)) for m in _VERB_WORD.finditer(sent)] if hits else []
        starts = [p for p, _ in verbs]
        prerequisite = _prerequisite_of(sent, tool)
        called = {n: _called(hits[n], verbs, starts) for n in hits}
        other_tool = any(ok for n, ok in called.items() if n != tool)

        # TS101: an instruction, graded by its target.
        severity = None
        if (
            re.search(TS101_ADDRESSED, sent, re.I)
            or re.search(TS101_OVERRIDE, sent, re.I)
            or re.search(TS101_TAMPER, sent, re.I)
        ):
            severity = "high"
        elif re.search(TS101_POSITIVE_ACT, sent, re.I):
            target = (
                _has_literal(sent)
                or re.search(OUTPUT_VERBS, sent, re.I) is not None
                or re.search(SENSITIVE_WORDS, sent, re.I) is not None
                or (other_tool and not prerequisite)
            )
            severity = "high" if target else "medium"
        elif re.search(TS101_NEGATIVE_ACT, sent, re.I):
            severity = "low"
        if severity is not None:
            add("TS101", s, e, {"high": _TS101_HIGH, "medium": _TS101_MEDIUM, "low": _TS101_LOW}[severity], severity)

        for m2 in re.finditer(TS102, sent, re.I):
            ident = m2.group("ident")
            value = m2.group("value")
            if value[:1] not in "'\"`":
                value = value.rstrip(".!?)")  # the sentence's own punctuation
            bare = value.strip("'\"`")
            sentinel = bool(re.fullmatch(SENTINEL, bare))
            if sentinel or (canonical_name(ident) in all_params and _literal_value(value)):
                add(
                    "TS102",
                    s,
                    e,
                    f"The sentence assigns the value {value} to {ident!r}. A value the user "
                    "never asked for, written into a call, is the argument hijack the study measured.",
                )
                break

        order = re.search(ORDER_WORDS, sent, re.I) is not None
        for name in sorted(hits, key=lambda n: idx.order.get(n, 0)):
            if not called[name]:
                continue
            if name == tool:
                if order and not prerequisite:
                    add(
                        "TS103",
                        s,
                        e,
                        f"The text tells the model to call this tool ({name}) before or besides what the user asked.",
                        "high",
                    )
                    break
                continue
            sev = "high" if order and not prerequisite else "medium"
            what = " as a prerequisite of this tool" if order and prerequisite else ""
            add("TS103", s, e, f"The text tells the model to call another tool ({name}){what}.", sev)
            break

        unknown = _unknown_identifiers(sent, known)
        if unknown:
            add(
                "TS104",
                s,
                e,
                "The text names "
                + ", ".join(repr(u) for u in unknown[:4])
                + ", which is not a parameter of this tool nor a tool in the catalogue.",
            )
        if (
            re.search(TS105_PHRASES, sent, re.I)
            or re.search(TS105_SILENT, sent, re.I)
            or re.search(TS105_EXFIL, sent, re.I)
            or re.search(TS105_PATHS, sent, re.I)
        ):
            add(
                "TS105",
                s,
                e,
                "The text asks for secrecy, for data to be sent to an address, or names a file that holds keys.",
            )
        if re.search(TS107_PHRASES, sent):
            add(
                "TS107",
                s,
                e,
                "The text claims authority over other instructions, a common frame for an injected instruction.",
            )
        elif re.search(TS107_CAPS, sent):
            loud = severity is not None and severity != "low"
            add(
                "TS107",
                s,
                e,
                "The text claims urgency beside an instruction."
                if loud
                else "The text uses an urgency word. Alone it is usually emphasis; shown at strict strictness only.",
                "medium" if loud else "low",
            )

    limit = TOOL_DESC_LIMIT if field == "description" else (PARAM_DESC_LIMIT if field.startswith("param:") else None)
    if limit is not None and len(text) > limit:
        add(
            "TS108",
            0,
            len(text),
            f"The text is {len(text):,} characters, over the {limit:,} this guard "
            "allows for this field (a heuristic threshold). Long text leaves room to hide an instruction. "
            "Stripping never removes it; review it by hand.",
        )
    return _ordered(out)


def _ordered(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (f.start, f.rule_id))


# --------------------------------------------------------------------------- #
# tools
# --------------------------------------------------------------------------- #


def _walk_params(params: Sequence[ParamIR], prefix: str = "") -> Iterator[tuple[str, ParamIR]]:
    for p in params:
        path = f"{prefix}.{p.name}" if prefix else p.name
        yield path, p
        yield from _walk_type(p.type, path)


def _walk_type(t: TypeIR | None, path: str) -> Iterator[tuple[str, ParamIR]]:
    if t is None:
        return
    if t.fields:
        yield from _walk_params(t.fields, path)
    if t.item is not None:
        yield from _walk_type(t.item, path + "[]")
    for u in t.union_of:
        yield from _walk_type(u, path)


def _enum_strings(t: TypeIR) -> list[str]:
    out: list[str] = []
    if t.kind == TypeKind.ENUM:
        out.extend(v for v in t.enum_values if isinstance(v, str))
    for u in t.union_of:
        out.extend(_enum_strings(u))
    if t.item is not None and t.item.kind == TypeKind.ENUM:
        out.extend(v for v in t.item.enum_values if isinstance(v, str))
    return out


def _walk_annotations(value: Any, key: str) -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield key, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _walk_annotations(v, f"{key}.{k}" if key else str(k))
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            yield from _walk_annotations(v, f"{key}[{i}]")


def tool_fields(tool: ToolIR) -> list[tuple[str, str]]:
    """Every scanned ``(field, text)`` of one tool, in scan order."""
    fields: list[tuple[str, str]] = [
        ("name", tool.name),
        ("description", tool.description),
        ("returns_description", tool.returns_description),
    ]
    for path, p in _walk_params(tool.params):
        fields.append((f"param:{path}", p.description))
        for v in _enum_strings(p.type):
            fields.append((f"enum:{path}", v))
        if isinstance(p.default, str):
            fields.append((f"default:{path}", p.default))
        if isinstance(p.example, str):
            fields.append((f"example:{path}", p.example))
    for key, text in _walk_annotations(tool.annotations or {}, ""):
        fields.append((f"annotation:{key}", text))
    return [(f, t) for f, t in fields if t]


def param_names_of(tool: ToolIR) -> list[str]:
    """Every parameter name of a tool, at any depth."""
    return [p.name for _, p in _walk_params(tool.params)]


def scan_tool(
    tool: ToolIR,
    *,
    catalogue_names: Sequence[str] = (),
    catalogue_params: Sequence[str] = (),
    index: CatalogueIndex | None = None,
) -> list[Finding]:
    """Every finding on one tool, at every severity, in field order."""
    params = param_names_of(tool)
    enums = [v for _, p in _walk_params(tool.params) for v in _enum_strings(p.type)]
    names = list(catalogue_names) or [tool.name]
    idx = index if index is not None else CatalogueIndex(names, catalogue_params)
    out: list[Finding] = []
    for fld, text in tool_fields(tool):
        out.extend(
            scan_text(
                text,
                tool=tool.name,
                field=fld,
                catalogue_names=names,
                param_names=params,
                other_param_names=catalogue_params,
                known_words=enums,
                index=idx,
            )
        )
    return out


def _facts() -> list[dict[str, Any]]:
    try:
        from ..advisor.evidence import load_evidence

        ev = load_evidence()
        out = []
        for fid in GUARD_FACT_IDS:
            try:
                f = ev.fact(fid)
            except Exception as exc:  # noqa: BLE001
                log.warning("guard: the study fact %s is missing from the evidence (%s)", fid, exc)
                continue
            out.append(
                {
                    "id": f["id"],
                    "value": f["value"],
                    "interval": f.get("interval"),
                    "text": f.get("text", ""),
                    "source": f.get("source", ""),
                }
            )
        return out
    except Exception as exc:  # noqa: BLE001 - the guard works without the evidence files
        log.warning("guard: the evidence could not be read, so reports carry no study facts (%s)", exc)
        return []


def scan_toolset(toolset: "Toolset", *, strictness: str = "standard") -> GuardReport:
    """Scan every tool; keep the findings at or above ``strictness``.

    ``lenient`` keeps high findings, ``standard`` high and medium, ``strict``
    all three.
    """
    if strictness not in STRICTNESS:
        raise ValueError(f"unknown strictness {strictness!r}; use one of {', '.join(STRICTNESS)}")
    keep = set(STRICTNESS[strictness])
    names = toolset.names()
    all_params = sorted({n for t in toolset for n in param_names_of(t)})
    index = CatalogueIndex(names, all_params)
    findings: list[Finding] = []
    for t in toolset:
        findings.extend(
            f
            for f in scan_tool(t, catalogue_names=names, catalogue_params=all_params, index=index)
            if f.severity in keep
        )
    flagged = [n for n in names if any(f.tool == n for f in findings)]
    counts = {s: sum(1 for f in findings if f.severity == s) for s in ("high", "medium", "low")}
    return GuardReport(
        strictness=strictness,
        n_tools=len(toolset),
        findings=findings,
        flagged_tools=flagged,
        counts=counts,
        action="report",
        removed=[],
        toolset=None,
        evidence=_facts(),
    )


__all__ = [
    "CatalogueIndex",
    "Finding",
    "GUARD_FACT_IDS",
    "GuardReport",
    "param_names_of",
    "scan_text",
    "scan_tool",
    "scan_toolset",
    "tool_fields",
]
