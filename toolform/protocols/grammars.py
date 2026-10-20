"""Grammars for constrained decoding.

One ablation needs the model to be physically unable to answer in the wrong
shape. The strongest objection to this whole study is that the differences
between formats are really "small models cannot produce valid JSON", which
constrained decoding solves in a line of config. Running the same cells with
and without a grammar splits the format effect into two halves we can report
separately:

* what disappears under constraint was **syntax** — the model knew the call and
  wrote it wrongly;
* what survives is **comprehension** — the model read the schema and picked the
  wrong tool or the wrong arguments.

Only protocols with an unambiguous machine-checkable shape get a grammar. The
rest return ``None`` and the runner leaves those cells unconstrained rather
than inventing a grammar that does not match what the parser accepts.

What the grammar pins down, and why it matters when reading the numbers: the
answer must be one JSON object (or an array of them) with a ``name`` drawn from
the tools actually in context and an ``arguments`` object. So the constrained
arm cannot produce a parse failure and cannot hallucinate a tool that does not
exist. Both of those are real failure modes we measure elsewhere; here they are
removed on purpose, and every table carrying this arm says so.
"""

from __future__ import annotations

from typing import Any

from ..ir import ToolIR, ToolUniverse

# Protocols whose accepted shape we can express exactly as a JSON schema.
CONSTRAINABLE = ("json_object", "json_array", "jsonl_call")


# How much of a call the grammar pins down:
#   names          the tool name is one of the universe's; `arguments` is any
#                  object (every constrained cell of the study ran this way)
#   typed          per tool, `arguments` carries that tool's parameters with
#                  their types, its required ones required, and nothing else:
#                  no invented argument *names*, defaults still possible
#   required_only  per tool, `arguments` may carry only the required
#                  parameters: an invented optional is impossible, and so is a
#                  stated one, which is the cost the arm measures
#   one_object     the typed call, and exactly one of it: no array, so a turn
#                  can carry one call and never the whole plan (the typed scope admits an array because json_object's
#                  own instructions allow one, and the agentic models used it
#                  to dump the plan)
GRAMMAR_SCOPES = ("names", "typed", "required_only", "one_object")


def _call_schema(names: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string", "enum": names},
            "arguments": {"type": "object"},
        },
        "required": ["name", "arguments"],
        "additionalProperties": False,
    }


def _arguments_schema(tool: ToolIR, *, required_only: bool) -> dict[str, Any]:
    from ..formats.common import type_to_json_schema

    props: dict[str, Any] = {}
    required: list[str] = []
    for p in tool.params:
        if required_only and not p.required:
            continue
        props[p.name] = type_to_json_schema(p.type, descriptions=False)
        if p.required:
            required.append(p.name)
    out: dict[str, Any] = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        out["required"] = required
    return out


def _typed_call_schema(universe: ToolUniverse, *, required_only: bool) -> dict[str, Any]:
    """One branch per tool: its name and its own arguments object."""
    branches = []
    for t in universe:
        branches.append(
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "enum": [t.name]},
                    "arguments": _arguments_schema(t, required_only=required_only),
                },
                "required": ["name", "arguments"],
                "additionalProperties": False,
            }
        )
    return {"anyOf": branches}


def json_schema_for(protocol_id: str, universe: ToolUniverse, scope: str = "names") -> dict[str, Any] | None:
    """The JSON schema a constrained answer must satisfy, or None.

    ``json_object`` accepts one object or an array of them, because that is
    what its own instructions ask for, so the schema is the union of the two.
    ``scope`` says how much of the call is pinned down (GRAMMAR_SCOPES).
    """
    if scope not in GRAMMAR_SCOPES:
        raise ValueError(f"unknown grammar scope {scope!r}; one of {GRAMMAR_SCOPES}")
    names = [t.name for t in universe]
    if not names:
        return None
    if scope == "names":
        call = _call_schema(names)
    else:
        call = _typed_call_schema(universe, required_only=scope == "required_only")
    if scope == "one_object":
        # One call per answer. json_object takes the bare object; the array
        # protocols keep their array but it holds exactly one call.
        if protocol_id == "json_object":
            return call
        if protocol_id in ("json_array", "jsonl_call"):
            return {"type": "array", "items": call, "minItems": 1, "maxItems": 1}
        return None
    if protocol_id == "json_object":
        return {"anyOf": [call, {"type": "array", "items": call, "minItems": 1}]}
    if protocol_id in ("json_array", "jsonl_call"):
        return {"type": "array", "items": call, "minItems": 1}
    return None


def grammar_for(protocol_id: str, universe: ToolUniverse, scope: str = "names") -> dict[str, Any] | None:
    """A backend-neutral grammar spec, or None when the protocol has none.

    The shape is deliberately small — ``{"kind": ..., "value": ...}`` — so a
    backend can map it onto whatever its own structured-output API is called
    this month without the runner knowing anything about vLLM.
    """
    schema = json_schema_for(protocol_id, universe, scope)
    if schema is None:
        return None
    return {"kind": "json_schema", "value": schema, "protocol_id": protocol_id, "scope": scope}
