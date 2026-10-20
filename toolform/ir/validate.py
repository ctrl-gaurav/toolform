"""Schema validation for model-produced calls.

Two things are checked and reported separately, because they answer different
research questions:

* **schema violation** — the call does not type-check against the tool
  (missing required arg, unknown arg, wrong type, enum member not in the set).
  This is the "did the model read the interface" signal.
* **correctness** — the call is not the gold call. Handled by the grader.

A call can be schema-valid but wrong, or schema-invalid but semantically
right; keeping them apart is what lets us say *how* a format fails.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .types import ToolCall, ToolIR, ToolUniverse, TypeIR, TypeKind, canonical_name


@dataclass
class ValidationReport:
    ok: bool = True
    unknown_tool: bool = False
    missing_required: list[str] = field(default_factory=list)
    unknown_args: list[str] = field(default_factory=list)
    type_errors: list[str] = field(default_factory=list)
    enum_errors: list[str] = field(default_factory=list)
    constraint_errors: list[str] = field(default_factory=list)

    def add(self, bucket: str, msg: str) -> None:
        getattr(self, bucket).append(msg)
        self.ok = False

    @property
    def n_errors(self) -> int:
        return (
            len(self.missing_required)
            + len(self.unknown_args)
            + len(self.type_errors)
            + len(self.enum_errors)
            + len(self.constraint_errors)
            + (1 if self.unknown_tool else 0)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "unknown_tool": self.unknown_tool,
            "missing_required": self.missing_required,
            "unknown_args": self.unknown_args,
            "type_errors": self.type_errors,
            "enum_errors": self.enum_errors,
            "constraint_errors": self.constraint_errors,
            "n_errors": self.n_errors,
        }


def _kind_ok(value: Any, kind: TypeKind) -> bool:
    if kind == TypeKind.ANY:
        return True
    if kind == TypeKind.STRING:
        return isinstance(value, str)
    if kind == TypeKind.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
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


def _validate_type(value: Any, spec: TypeIR, path: str, report: ValidationReport) -> None:
    kind = spec.kind

    if kind == TypeKind.ENUM:
        base = spec.base or TypeKind.STRING
        if not _kind_ok(value, base):
            report.add("type_errors", f"{path}: expected {base.value}, got {type(value).__name__}")
            return
        if spec.enum_values and value not in spec.enum_values:
            # Protobuf, Avro and GraphQL render enum members in SCREAMING_CASE
            # because those languages do, and a model that echoes `PROD` for a
            # member the schema showed it as PROD has chosen the right member.
            # Case is never a semantic difference in this study's enums.
            folded = {str(m).lower() for m in spec.enum_values}
            if not (isinstance(value, str) and value.lower() in folded):
                report.add(
                    "enum_errors",
                    f"{path}: {value!r} not in {list(spec.enum_values)}",
                )
        return

    if kind == TypeKind.UNION:
        for branch in spec.union_of:
            sub = ValidationReport()
            _validate_type(value, branch, path, sub)
            if sub.ok:
                return
        report.add("type_errors", f"{path}: no union branch accepts {value!r}")
        return

    if not _kind_ok(value, kind):
        report.add(
            "type_errors",
            f"{path}: expected {kind.value}, got {type(value).__name__}",
        )
        return

    if kind == TypeKind.ARRAY and spec.item is not None:
        for i, v in enumerate(value):
            _validate_type(v, spec.item, f"{path}[{i}]", report)

    if kind == TypeKind.OBJECT and spec.fields:
        by_canon = {canonical_name(f.name): f for f in spec.fields}
        supplied = {canonical_name(k) for k in value}
        for f in spec.fields:
            if f.required and canonical_name(f.name) not in supplied:
                report.add("missing_required", f"{path}.{f.name}")
        for k, v in value.items():
            sub = by_canon.get(canonical_name(k))
            if sub is None:
                report.add("unknown_args", f"{path}.{k}")
            else:
                _validate_type(v, sub.type, f"{path}.{k}", report)

    c = spec.constraints
    if c.minimum is not None and isinstance(value, (int, float)) and value < c.minimum:
        report.add("constraint_errors", f"{path}: {value} < minimum {c.minimum}")
    if c.maximum is not None and isinstance(value, (int, float)) and value > c.maximum:
        report.add("constraint_errors", f"{path}: {value} > maximum {c.maximum}")
    if c.min_length is not None and isinstance(value, str) and len(value) < c.min_length:
        report.add("constraint_errors", f"{path}: shorter than {c.min_length}")
    if c.max_length is not None and isinstance(value, str) and len(value) > c.max_length:
        report.add("constraint_errors", f"{path}: longer than {c.max_length}")
    if c.min_items is not None and isinstance(value, (list, tuple)) and len(value) < c.min_items:
        report.add("constraint_errors", f"{path}: fewer than {c.min_items} items")
    if c.max_items is not None and isinstance(value, (list, tuple)) and len(value) > c.max_items:
        report.add("constraint_errors", f"{path}: more than {c.max_items} items")


def validate_call(call: ToolCall, tool: ToolIR | None) -> ValidationReport:
    """Type-check one call against its tool spec."""
    report = ValidationReport()
    if tool is None:
        report.unknown_tool = True
        report.ok = False
        return report

    # Resolve argument names across naming conventions, the same way the
    # universe resolves tool names. A Swift rendering shows `startHour`, and a
    # model answering with what it was shown has not invented an argument nor
    # omitted the required one.
    supplied = {canonical_name(k) for k in call.arguments}
    for p in tool.params:
        if p.required and canonical_name(p.name) not in supplied:
            report.add("missing_required", p.name)

    for k, v in call.arguments.items():
        p = tool.param(k)
        if p is None:
            report.add("unknown_args", k)
            continue
        if v is None and not p.required:
            continue
        _validate_type(v, p.type, k, report)

    return report


def validate_calls(calls: list[ToolCall], universe: ToolUniverse) -> list[ValidationReport]:
    return [validate_call(c, universe.get(c.name)) for c in calls]


def hallucinated_tool(call: ToolCall, universe: ToolUniverse) -> bool:
    """True when the model invented a tool name that is not on offer."""
    return universe.get(call.name) is None
