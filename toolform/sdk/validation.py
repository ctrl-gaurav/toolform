"""Argument validation for the SDK: the study's validator plus two JSON Schema rules it leaves out.

:func:`toolform.ir.validate_call` is the validator the study graded with, and
the SDK keeps its verdicts. It does not check ``pattern``, and it counts a
float such as ``5.0`` as a wrong type for an integer, where JSON Schema counts
any number with a zero fraction as an integer. This module adds both:

* an integral float given for an integer is read as that integer before the
  study's validator runs, so ``days: 5.0`` passes and its bounds are checked;
* every string whose schema carries a ``pattern`` is matched with
  :func:`re.search`, as JSON Schema does (the pattern is not anchored for you).
  A pattern Python's ``re`` cannot compile is skipped, never reported.

Inside a union the first branch that accepts the value is the one checked.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from ..ir import ToolCall, ToolIR, TypeIR, TypeKind, ValidationReport, validate_call
from ..ir.types import canonical_name


def _integral(value: Any) -> bool:
    return isinstance(value, float) and value.is_integer()


def _accepts(value: Any, t: TypeIR) -> bool:
    """Whether ``value`` has the basic kind of ``t`` (no constraints)."""
    kind = t.kind
    if kind == TypeKind.ENUM:
        return value in t.enum_values or (
            isinstance(value, str) and value.lower() in {str(v).lower() for v in t.enum_values}
        )
    if kind == TypeKind.UNION:
        return any(_accepts(value, b) for b in t.union_of)
    if kind == TypeKind.STRING:
        return isinstance(value, str)
    if kind == TypeKind.INTEGER:
        return (isinstance(value, int) and not isinstance(value, bool)) or _integral(value)
    if kind == TypeKind.NUMBER:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == TypeKind.BOOLEAN:
        return isinstance(value, bool)
    if kind == TypeKind.ARRAY:
        return isinstance(value, (list, tuple))
    if kind == TypeKind.OBJECT:
        return isinstance(value, dict)
    if kind == TypeKind.NULL:
        return value is None
    return True


def _branch(value: Any, t: TypeIR) -> TypeIR | None:
    if t.kind != TypeKind.UNION:
        return t
    for b in t.union_of:
        if _accepts(value, b):
            return _branch(value, b)
    return None


def _field(t: TypeIR, key: str) -> TypeIR | None:
    want = canonical_name(key)
    for f in t.fields:
        if canonical_name(f.name) == want:
            return f.type
    return None


def _normalize(value: Any, t: TypeIR | None) -> Any:
    """``value`` with integral floats turned into ints wherever the schema says integer."""
    if t is None:
        return value
    b = _branch(value, t)
    if b is None:
        return value
    if b.kind == TypeKind.INTEGER and _integral(value):
        return int(value)
    if b.kind == TypeKind.ENUM and (b.base == TypeKind.INTEGER) and _integral(value):
        return int(value)
    if b.kind == TypeKind.ARRAY and isinstance(value, (list, tuple)) and b.item is not None:
        return [_normalize(v, b.item) for v in value]
    if b.kind == TypeKind.OBJECT and isinstance(value, dict) and b.fields:
        return {k: _normalize(v, _field(b, k)) for k, v in value.items()}
    return value


@lru_cache(maxsize=512)
def _compiled(pattern: str) -> re.Pattern[str] | None:
    try:
        return re.compile(pattern)
    except re.error:
        return None


def _patterns(value: Any, t: TypeIR | None, path: str, out: list[str]) -> None:
    if t is None:
        return
    b = _branch(value, t)
    if b is None:
        return
    pat = b.constraints.pattern
    if pat and isinstance(value, str):
        rx = _compiled(pat)
        if rx is not None and rx.search(value) is None:
            out.append(f"{path}: {value!r} does not match pattern {pat!r}")
    if b.kind == TypeKind.ARRAY and isinstance(value, (list, tuple)) and b.item is not None:
        for i, v in enumerate(value):
            _patterns(v, b.item, f"{path}[{i}]", out)
    if b.kind == TypeKind.OBJECT and isinstance(value, dict):
        for k, v in value.items():
            _patterns(v, _field(b, k), f"{path}.{k}", out)


def validate_tool_call(call: ToolCall, tool: ToolIR | None) -> ValidationReport:
    """Validate ``call`` against ``tool``: the study's checks, integral floats as integers, and patterns."""
    if tool is None:
        return validate_call(call, None)
    args = {}
    for k, v in call.arguments.items():
        p = tool.param(k)
        args[k] = _normalize(v, p.type) if p is not None else v
    report = validate_call(ToolCall(name=call.name, arguments=args), tool)
    problems: list[str] = []
    for k, v in args.items():
        p = tool.param(k)
        if p is not None and not (v is None and not p.required):
            _patterns(v, p.type, k, problems)
    for msg in problems:
        report.add("constraint_errors", msg)
    return report


__all__ = ["validate_tool_call"]
