"""The lenient parser: accept a call written in any known protocol.

Every response is parsed twice. The strict pass uses only the protocol the
model was asked for. The lenient pass tries all of them in a fixed priority
order and takes the first that yields a call.

Two numbers come out of this and both are reported:

* **task accuracy** — computed from the strict parse (the protocol was part of
  the instruction, so ignoring it is a real failure).
* **format compliance** — strict-parse-succeeded / lenient-parse-succeeded. A
  model that always gets the call right but never in the requested shape shows
  up as high lenient accuracy and low compliance, which is a different finding
  from being unable to do the task.

Reporting both is what stops the parser from becoming the experiment.
"""

from __future__ import annotations

from ..ir import ToolUniverse
from .base import ParseResult, declares_no_call, get_protocol

#: Tried in this order. Structured, unambiguous syntaxes first; prose last,
#: because the prose adapter is the most willing to guess.
LENIENT_ORDER = (
    "native",
    "tool_call_tags",
    "function_tags",
    "xml_call",
    "code_block_json",
    "json_object",
    "json_array",
    "jsonl_call",
    "python_tag",
    "python_list_call",
    "python_call",
    "bracket_call",
    "react",
    "yaml_call",
    "toml_call",
    "sexpr_call",
    "sql_call",
    "graphql_call",
    "url_call",
    "cli_call",
    "two_step_call",
    "table_call",
    "key_value_call",
    "pipe_call",
    "symbolic_call",
    "csv_call",
    "slot_fill_call",
    "xml_generic_call",
    "nl_intent_structured",
    "nl_intent",
)


def parse_lenient(text: str, universe: ToolUniverse, *, skip: str | None = None) -> ParseResult:
    """Try every protocol in priority order; return the first that parses."""
    tried = 0
    for pid in LENIENT_ORDER:
        if pid == skip:
            continue
        try:
            proto = get_protocol(pid)
        except KeyError:
            continue
        tried += 1
        try:
            res = proto.parse(text, universe)
        except Exception:  # noqa: BLE001 - a broken parse is just a miss
            continue
        if res.calls:
            # only accept a call naming a tool that is actually on offer,
            # otherwise a greedy parser can manufacture calls from prose
            if any(universe.get(c.name) is not None for c in res.calls):
                return ParseResult(
                    calls=res.calls,
                    ok=True,
                    mode="lenient",
                    matched_syntax=pid,
                    note=res.note,
                    n_candidates=tried,
                )
    if declares_no_call(text):
        return ParseResult(calls=[], ok=True, mode="lenient", matched_syntax="explicit-no-call", n_candidates=tried)
    return ParseResult(calls=[], ok=False, mode="lenient", n_candidates=tried)


def parse_both(text: str, universe: ToolUniverse, protocol_id: str) -> tuple[ParseResult, ParseResult]:
    """Return ``(strict, lenient)`` parses of the same response."""
    proto = get_protocol(protocol_id)
    try:
        strict = proto.parse(text, universe)
    except Exception as exc:  # noqa: BLE001
        strict = ParseResult(calls=[], ok=False, mode="strict", note=f"error:{exc}")
    strict.mode = "strict"
    if strict.calls:
        lenient = ParseResult(
            calls=list(strict.calls),
            ok=True,
            mode="lenient",
            matched_syntax=protocol_id,
            note=strict.note,
        )
    else:
        lenient = parse_lenient(text, universe)
    return strict, lenient
