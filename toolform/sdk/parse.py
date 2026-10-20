"""Read a model's reply under a protocol and one of the study's three grading rules.

The rules differ only in how they treat an argument the model wrote flat that
belongs inside an object:

``main``        each protocol's own strict parser. The text protocols (XML
                call, natural language, key-value, command line, URL, tags)
                re-nest the flat argument; typed protocols never do.
``symmetric``   the same re-nesting repair applied under every protocol.
``as_written``  no repair: a reply whose parse needed re-nesting is rejected.

The paper uses ``main`` for its headline, recommends ``symmetric`` for
measurement, and reports ``as_written`` as the strictest reading.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from ..ir import ToolCall, ToolUniverse, ValidationReport, normalize_call
from ..protocols import declares_no_call, parse_both, protocol_ids, strip_reasoning
from ..protocols.base import NO_CALL_PHRASES
from ..protocols.structure import recover_structure
from .constants import check_rule
from .errors import UnknownProtocolError
from .toolset import Toolset
from .validation import validate_tool_call

AS_WRITTEN_REASON = "the parser re-nested a flat argument; not accepted as written"

#: Phrases that make a reply with no call a declaration that no tool applies (the study's list,
#: matched case-insensitively anywhere in the reply once any reasoning block is removed).
NO_CALL_DECLARATIONS: tuple[str, ...] = tuple(NO_CALL_PHRASES)

_ASCII_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


@dataclass
class ParsedCall:
    """One call read from a reply, with what the rule and the validator made of it."""

    name: str
    arguments: dict[str, Any]
    resolved_name: str | None
    normalized_arguments: dict[str, Any] | None
    valid: bool
    validation: dict[str, Any]
    repairs: list[str] = field(default_factory=list)
    accepted: bool = True
    reason: str = ""

    def to_call(self) -> ToolCall:
        """The call as a :class:`~toolform.ir.ToolCall`, under the toolset's spelling of the name."""
        return ToolCall(name=self.resolved_name or self.name, arguments=dict(self.arguments))

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable dict of every field."""
        return {
            "name": self.name,
            "arguments": self.arguments,
            "resolved_name": self.resolved_name,
            "normalized_arguments": self.normalized_arguments,
            "valid": self.valid,
            "validation": self.validation,
            "repairs": list(self.repairs),
            "accepted": self.accepted,
            "reason": self.reason,
        }


@dataclass
class ParsedReply:
    """Everything read from one reply."""

    protocol_id: str
    rule: str
    calls: list[ParsedCall]
    rejected: list[ParsedCall]
    parsed_strict: bool
    parsed_lenient: bool
    matched_syntax: str
    format_compliant: bool
    no_call_declared: bool
    hallucinated: list[str]
    reasoning_removed: bool
    note: str

    @property
    def ok(self) -> bool:
        """Nothing was rejected and no tool was invented, and either every accepted call is valid
        or there is no call and the reply said no tool applies (see :data:`NO_CALL_DECLARATIONS`)."""
        if self.rejected or self.hallucinated:
            return False
        if self.calls:
            return all(c.valid for c in self.calls)
        return self.no_call_declared

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable dict of every field, with ``ok``."""
        return {
            "protocol_id": self.protocol_id,
            "rule": self.rule,
            "ok": self.ok,
            "calls": [c.to_dict() for c in self.calls],
            "rejected": [c.to_dict() for c in self.rejected],
            "parsed_strict": self.parsed_strict,
            "parsed_lenient": self.parsed_lenient,
            "matched_syntax": self.matched_syntax,
            "format_compliant": self.format_compliant,
            "no_call_declared": self.no_call_declared,
            "hallucinated": list(self.hallucinated),
            "reasoning_removed": self.reasoning_removed,
            "note": self.note,
        }


def validate_arguments(call: ToolCall | Mapping[str, Any], toolset: Toolset) -> ValidationReport:
    """Type-check one call against the toolset's schema.

    The study's validator (``toolform.ir.validate_call``), plus ``pattern``
    and integral floats for integers (:mod:`toolform.sdk.validation`).
    """
    c = call if isinstance(call, ToolCall) else ToolCall.from_dict(dict(call))
    tool = toolset.get(c.name)
    name = tool.name if tool is not None else c.name
    return validate_tool_call(ToolCall(name=name, arguments=dict(c.arguments)), tool)


def _json_values(text: str) -> int:
    """How many JSON values stand one after another in ``text`` (0 when it is not JSON at all)."""
    dec = json.JSONDecoder()
    i, n, count = 0, len(text), 0
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        try:
            _, i = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            return count
        count += 1
    return count


def _needs_unicode_reader(universe: ToolUniverse) -> bool:
    return any(t.name.isidentifier() and not _ASCII_IDENT.match(t.name) for t in universe.tools)


def _unicode_python_calls(text: str, universe: ToolUniverse) -> list[ToolCall]:
    """Calls such as ``天气_查询(城市="北京")``: the python_call syntax with non-ASCII names.

    The study's parser reads ASCII identifiers only. This reader uses Python's
    own grammar, which accepts any identifier, and keeps only calls whose
    arguments are literals and whose function names a tool of the set.
    """
    body = strip_reasoning(text).strip()
    fence = re.search(r"```(?:python|py)?\s*\n(.*?)```", body, re.S)
    if fence:
        body = fence.group(1)
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return []
    calls: list[ToolCall] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if universe.get(node.func.id) is None:
            continue
        args: dict[str, Any] = {}
        try:
            for kw in node.keywords:
                if kw.arg is None:
                    raise ValueError("**kwargs")
                args[kw.arg] = ast.literal_eval(kw.value)
        except (ValueError, SyntaxError):
            continue
        if node.args:
            continue
        calls.append(ToolCall(name=node.func.id, arguments=args))
    return calls


def parse_reply(
    text: str,
    toolset: Toolset,
    protocol_id: str,
    *,
    rule: str = "main",
    validate: bool = True,
    lenient_fallback: bool = False,
) -> ParsedReply:
    """Parse ``text`` with ``protocol_id``'s strict parser under ``rule``.

    ``lenient_fallback=True`` takes the calls from any protocol's syntax when
    the strict parser finds none, each marked with the repair
    ``lenient:<syntax>``; it is refused under ``as_written``. With
    ``validate=True`` each accepted call is checked against the schema;
    an invalid call stays in ``calls`` with ``valid=False``.
    """
    check_rule(rule)
    if protocol_id not in protocol_ids():
        raise UnknownProtocolError(protocol_id, protocol_ids())
    if lenient_fallback and rule == "as_written":
        raise ValueError("lenient_fallback is a repair; it cannot be used under the as_written rule")
    text = text or ""
    universe = toolset.universe
    strict, lenient = parse_both(text, universe, protocol_id)
    source_calls = list(strict.calls)
    note = strict.note or ""
    parsed_strict = bool(strict.calls)
    notes: list[str] = []
    if not source_calls and protocol_id == "python_call" and _needs_unicode_reader(universe):
        uni = _unicode_python_calls(text, universe)
        if uni:
            source_calls, parsed_strict = uni, True
            notes.append("read with the SDK's reader for non-ASCII names; the study's parser reads ASCII names only")
    if protocol_id == "json_object" and len(strict.calls) == 1:
        n_values = _json_values(strip_reasoning(text).strip())
        if n_values > 1:
            notes.append(
                f"the reply holds {n_values} JSON objects one after another; json_object reads the "
                f"first only. Ask for one JSON array (json_array) to allow several calls"
            )
    base_repairs: list[str] = []
    if not source_calls and lenient_fallback and lenient.calls:
        source_calls = list(lenient.calls)
        note = lenient.note or ""
        base_repairs = [f"lenient:{lenient.matched_syntax}"]
    renested = "renested" in note

    accepted: list[ParsedCall] = []
    rejected: list[ParsedCall] = []
    hallucinated: list[str] = []
    for c in source_calls:
        tool = universe.get(c.name)
        args = dict(c.arguments) if isinstance(c.arguments, dict) else {"_raw": c.arguments}
        repairs = list(base_repairs)
        if renested:
            repairs.append("renested")
        if rule == "symmetric" and tool is not None:
            moved: list[str] = []
            args = recover_structure(dict(args), tool, moved)
            for k in moved:
                if k.endswith("!conflict"):
                    repairs.append(f"conflict:{k[: -len('!conflict')]}")
                else:
                    repairs.append(f"renested:{k}")
        ok_rule = True
        reason = ""
        if tool is None:
            ok_rule = False
            reason = "unknown tool"
            hallucinated.append(c.name)
        elif rule == "as_written" and renested:
            ok_rule = False
            reason = AS_WRITTEN_REASON
        call = ToolCall(name=tool.name if tool is not None else c.name, arguments=args)
        if tool is None:
            report = validate_tool_call(call, None)
            valid = False
            normalized = None
        else:
            report = validate_tool_call(call, tool) if validate else ValidationReport()
            valid = report.ok
            normalized = normalize_call(call, tool, strictness="normalized").arguments
        pc = ParsedCall(
            name=c.name,
            arguments=args,
            resolved_name=tool.name if tool is not None else None,
            normalized_arguments=normalized,
            valid=valid,
            validation=report.to_dict(),
            repairs=repairs,
            accepted=ok_rule,
            reason=reason,
        )
        (accepted if ok_rule else rejected).append(pc)

    return ParsedReply(
        protocol_id=protocol_id,
        rule=rule,
        calls=accepted,
        rejected=rejected,
        parsed_strict=parsed_strict,
        parsed_lenient=bool(lenient.calls) or parsed_strict,
        matched_syntax=strict.matched_syntax or lenient.matched_syntax or (protocol_id if parsed_strict else ""),
        format_compliant=parsed_strict if (lenient.calls or parsed_strict) else True,
        no_call_declared=declares_no_call(text),
        hallucinated=hallucinated,
        reasoning_removed=strip_reasoning(text) != text,
        note="; ".join(x for x in [note, *notes] if x),
    )


__all__ = [
    "AS_WRITTEN_REASON",
    "NO_CALL_DECLARATIONS",
    "ParsedCall",
    "ParsedReply",
    "parse_reply",
    "validate_arguments",
]
