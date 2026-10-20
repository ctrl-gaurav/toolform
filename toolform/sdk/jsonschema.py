"""JSON Schema to the canonical IR, keeping constraints.

The study's converter for public benchmarks drops
constraints, which was right for the public benchmarks and is wrong for user
tools: most renderers show constraints (XML writes "Value must be at least 1 and
at most 600"), so dropping them changes what the model reads.

Rules, in the order they apply to one schema node:

* ``$ref`` is resolved against ``$defs`` or ``definitions``. Past a depth of 12
  the node becomes ``ANY``, so a recursive schema cannot loop.
* ``allOf`` with one branch is that branch; several object branches are merged.
* ``anyOf`` or ``oneOf`` with one non-null branch is that branch, and the
  parameter becomes optional; several branches make a ``UNION``.
* ``type: [x, "null"]`` is ``x`` and the parameter becomes optional.
* ``enum`` makes an ``ENUM``; its base is the declared type, else the type of
  the values. ``const`` makes a one-value ``ENUM``.
* ``array`` reads ``items``; ``object`` or ``properties`` makes an ``OBJECT``
  with its own ``required`` list.
* ``minimum``, ``maximum``, ``minLength``, ``maxLength``, ``minItems``,
  ``maxItems``, ``pattern`` and ``format`` become constraints. The IR has no
  exclusive bound, so ``exclusiveMinimum`` and ``exclusiveMaximum`` (numeric
  form) are stored as ``minimum`` and ``maximum``.
* ``default`` and ``examples[0]`` become ``ParamIR.default`` and
  ``ParamIR.example``.

A nullable parameter is treated as optional in both forms above. That is a
decision of this module: a validator then accepts an explicit ``null``, which
is what a nullable schema allows.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Mapping

from ..ir import Constraints, ParamIR, ToolIR, TypeIR, TypeKind

MAX_REF_DEPTH = 12

#: Where the loader collects what it could not read faithfully; None outside :func:`schema_warnings`.
_SINK: ContextVar[list[str] | None] = ContextVar("toolform_schema_warnings", default=None)


@contextmanager
def schema_warnings() -> Iterator[list[str]]:
    """Collect the loader's warnings (an unknown ``type`` read as any value, say) while converting."""
    sink: list[str] = []
    token = _SINK.set(sink)
    try:
        yield sink
    finally:
        _SINK.reset(token)


def _warn(message: str) -> None:
    sink = _SINK.get()
    if sink is not None and message not in sink:
        sink.append(message)


_SCALARS = {
    "string": TypeKind.STRING,
    "integer": TypeKind.INTEGER,
    "number": TypeKind.NUMBER,
    "boolean": TypeKind.BOOLEAN,
    "null": TypeKind.NULL,
}


def _constraints(spec: Mapping[str, Any]) -> Constraints:
    def num(key: str) -> float | int | None:
        v = spec.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        return v

    def whole(key: str) -> int | None:
        v = spec.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        return int(v)

    minimum = num("minimum")
    if minimum is None:
        minimum = num("exclusiveMinimum")
    maximum = num("maximum")
    if maximum is None:
        maximum = num("exclusiveMaximum")
    pattern = spec.get("pattern") if isinstance(spec.get("pattern"), str) else None
    fmt = spec.get("format") if isinstance(spec.get("format"), str) else None
    return Constraints(
        minimum=minimum,
        maximum=maximum,
        min_length=whole("minLength"),
        max_length=whole("maxLength"),
        min_items=whole("minItems"),
        max_items=whole("maxItems"),
        pattern=pattern,
        format=fmt,
    )


def _resolve_ref(ref: str, defs: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for prefix in ("#/$defs/", "#/definitions/"):
        if ref.startswith(prefix):
            key = ref[len(prefix) :]
            target = defs.get(key)
            return target if isinstance(target, Mapping) else None
    # A bare name is accepted too; some generators write "$ref": "Address".
    target = defs.get(ref)
    return target if isinstance(target, Mapping) else None


def _is_null(spec: Any) -> bool:
    return isinstance(spec, Mapping) and (
        spec.get("type") == "null" or spec.get("const", 0) is None and "const" in spec
    )


def _merge_all_of(branches: list[Mapping[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    props: dict[str, Any] = {}
    required: list[str] = []
    for b in branches:
        for k, v in b.items():
            if k == "properties" and isinstance(v, Mapping):
                props.update(v)
            elif k == "required" and isinstance(v, list):
                required.extend(x for x in v if x not in required)
            elif k not in out:
                out[k] = v
    if props:
        out["properties"] = props
        out.setdefault("type", "object")
    if required:
        out["required"] = required
    return out


def _nullable_and_core(spec: Mapping[str, Any], defs: Mapping[str, Any], depth: int) -> tuple[Mapping[str, Any], bool]:
    """Strip one level of nullability; return the remaining schema and whether it was nullable."""
    if "$ref" in spec and isinstance(spec["$ref"], str):
        if depth >= MAX_REF_DEPTH:
            return {}, False
        target = _resolve_ref(spec["$ref"], defs)
        if target is None:
            return {}, False
        # Sibling keywords (description, default) sit beside $ref; keep them.
        merged = dict(target)
        for k, v in spec.items():
            if k != "$ref":
                merged.setdefault(k, v)
        return _nullable_and_core(merged, defs, depth + 1)
    for key in ("anyOf", "oneOf"):
        branches = spec.get(key)
        if isinstance(branches, list) and branches:
            non_null = [b for b in branches if not _is_null(b)]
            nullable = len(non_null) < len(branches)
            if len(non_null) == 1:
                core = dict(non_null[0]) if isinstance(non_null[0], Mapping) else {}
                for k, v in spec.items():
                    if k not in (key,):
                        core.setdefault(k, v)
                inner, inner_null = _nullable_and_core(core, defs, depth)
                return inner, nullable or inner_null
            if nullable:
                rest = {k: v for k, v in spec.items() if k != key}
                rest[key] = non_null
                return rest, True
    t = spec.get("type")
    if isinstance(t, list):
        non_null_t = [x for x in t if x != "null"]
        if len(non_null_t) < len(t):
            rest = dict(spec)
            rest["type"] = non_null_t[0] if len(non_null_t) == 1 else non_null_t
            return rest, True
    if isinstance(spec.get("enum"), list) and None in spec["enum"]:
        rest = dict(spec)
        rest["enum"] = [v for v in spec["enum"] if v is not None]
        return rest, True
    return spec, False


def _enum_base(values: list[Any], declared: Any) -> TypeKind:
    if isinstance(declared, str) and declared in ("integer", "number", "string", "boolean"):
        return _SCALARS[declared]
    if values and all(isinstance(v, bool) for v in values):
        return TypeKind.BOOLEAN
    if values and all(isinstance(v, int) and not isinstance(v, bool) for v in values):
        return TypeKind.INTEGER
    if values and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
        return TypeKind.NUMBER
    return TypeKind.STRING


def _type_core(spec: Mapping[str, Any], defs: Mapping[str, Any], depth: int) -> TypeIR:
    if depth > MAX_REF_DEPTH:
        return TypeIR(kind=TypeKind.ANY)
    c = _constraints(spec)
    all_of = spec.get("allOf")
    if isinstance(all_of, list) and all_of:
        branches = []
        for b in all_of:
            if isinstance(b, Mapping):
                core, _ = _nullable_and_core(b, defs, depth + 1)
                branches.append(core)
        merged = branches[0] if len(branches) == 1 else _merge_all_of(branches)
        rest = {k: v for k, v in spec.items() if k != "allOf"}
        for k, v in rest.items():
            merged = dict(merged)
            merged.setdefault(k, v)
        return type_from_json_schema(merged, defs, depth=depth + 1)
    for key in ("anyOf", "oneOf"):
        alts = spec.get(key)
        if isinstance(alts, list) and len(alts) > 1:
            return TypeIR(
                kind=TypeKind.UNION,
                union_of=tuple(
                    type_from_json_schema(b if isinstance(b, Mapping) else {}, defs, depth=depth + 1) for b in alts
                ),
            )
    if "const" in spec:
        v = spec["const"]
        return TypeIR(kind=TypeKind.ENUM, enum_values=(v,), base=_enum_base([v], spec.get("type")), constraints=c)
    if isinstance(spec.get("enum"), list):
        values = list(spec["enum"])
        return TypeIR(
            kind=TypeKind.ENUM, enum_values=tuple(values), base=_enum_base(values, spec.get("type")), constraints=c
        )
    t = spec.get("type")
    if isinstance(t, list):
        if len(t) == 1:
            t = t[0]
        else:
            return TypeIR(
                kind=TypeKind.UNION,
                union_of=tuple(
                    type_from_json_schema(
                        {**{k: v for k, v in spec.items() if k != "type"}, "type": x}, defs, depth=depth + 1
                    )
                    for x in t
                ),
            )
    if t == "array" or (t is None and "items" in spec):
        items = spec.get("items")
        if isinstance(items, list):  # tuple form: one item type per position
            items = items[0] if len(items) == 1 else ({"anyOf": items} if items else None)
        item = type_from_json_schema(items, defs, depth=depth + 1) if isinstance(items, Mapping) else None
        return TypeIR(kind=TypeKind.ARRAY, item=item, constraints=c)
    if t == "object" or (t is None and isinstance(spec.get("properties"), Mapping)):
        fields = params_from_json_schema(spec, defs=defs, depth=depth + 1)
        return TypeIR(kind=TypeKind.OBJECT, fields=fields, constraints=c)
    if isinstance(t, str) and t in _SCALARS:
        return TypeIR(kind=_SCALARS[t], constraints=c)
    if t is not None:
        _warn(f"unknown JSON Schema type {t!r}, read as any value")
    return TypeIR(kind=TypeKind.ANY, constraints=c)


def type_from_json_schema(
    spec: Mapping[str, Any] | None, defs: Mapping[str, Any] | None = None, *, depth: int = 0
) -> TypeIR:
    """Convert one JSON Schema node into a :class:`~toolform.ir.TypeIR`.

    ``defs`` holds the ``$defs`` or ``definitions`` of the enclosing document.
    Nullability is dropped here; use :func:`params_from_json_schema` to keep it
    as the parameter's optional flag.
    """
    if not isinstance(spec, Mapping) or depth > MAX_REF_DEPTH:
        return TypeIR(kind=TypeKind.ANY)
    defs = defs or {}
    core, _ = _nullable_and_core(spec, defs, depth)
    if not core:
        return TypeIR(kind=TypeKind.ANY)
    return _type_core(core, defs, depth)


def _param(name: str, spec: Any, required: bool, defs: Mapping[str, Any], depth: int) -> ParamIR:
    if not isinstance(spec, Mapping):
        return ParamIR(name=name, type=TypeIR(kind=TypeKind.ANY), required=required)
    core, nullable = _nullable_and_core(spec, defs, depth)
    t = _type_core(core, defs, depth) if core else TypeIR(kind=TypeKind.ANY)
    description = spec.get("description")
    if not isinstance(description, str):
        description = core.get("description") if isinstance(core.get("description"), str) else ""
    default = spec["default"] if "default" in spec else core.get("default")
    examples = spec.get("examples", core.get("examples"))
    example = examples[0] if isinstance(examples, list) and examples else None
    return ParamIR(
        name=str(name),
        type=t,
        description=description or "",
        required=bool(required and not nullable),
        default=default,
        example=example,
    )


def params_from_json_schema(
    parameters: Mapping[str, Any] | None, *, defs: Mapping[str, Any] | None = None, depth: int = 0
) -> tuple[ParamIR, ...]:
    """The parameters of an object schema, in property order, with required flags."""
    if not isinstance(parameters, Mapping):
        return ()
    local_defs: dict[str, Any] = dict(defs or {})
    for key in ("$defs", "definitions"):
        if isinstance(parameters.get(key), Mapping):
            local_defs.update(parameters[key])
    core, _ = _nullable_and_core(parameters, local_defs, depth)
    if isinstance(core.get("allOf"), list):
        core = _merge_all_of(
            [b for b in core["allOf"] if isinstance(b, Mapping)] + [{k: v for k, v in core.items() if k != "allOf"}]
        )
    props = core.get("properties")
    if not isinstance(props, Mapping):
        return ()
    required = core.get("required")
    req = set(required) if isinstance(required, list) else set()
    return tuple(_param(str(k), v, k in req, local_defs, depth) for k, v in props.items())


def tool_from_function_schema(
    name: str,
    description: str,
    parameters: Mapping[str, Any] | None,
    *,
    origin: str = "user",
    annotations: Mapping[str, Any] | None = None,
    returns: Mapping[str, Any] | None = None,
) -> ToolIR:
    """Build a :class:`~toolform.ir.ToolIR` from a function's name, description and parameter schema.

    ``returns`` is an optional JSON Schema of the result (an OpenAI ``returns``
    or an MCP ``outputSchema``); its ``description`` becomes
    ``returns_description``.
    """
    defs: dict[str, Any] = {}
    if isinstance(parameters, Mapping):
        for key in ("$defs", "definitions"):
            if isinstance(parameters.get(key), Mapping):
                defs.update(parameters[key])
    sink = _SINK.get()
    before = len(sink) if sink is not None else 0
    ret_type: TypeIR | None = None
    ret_desc = ""
    if isinstance(returns, Mapping) and returns:
        ret_type = type_from_json_schema(returns, defs)
        if isinstance(returns.get("description"), str):
            ret_desc = returns["description"]
    params = params_from_json_schema(parameters, defs=defs)
    if sink is not None:
        sink[before:] = [f"tool {name!r}: {m}" for m in sink[before:]]
    return ToolIR(
        name=str(name),
        description=description or "",
        params=params,
        returns=ret_type,
        returns_description=ret_desc,
        domain="user",
        category="user",
        origin=origin,
        kernel=None,
        annotations=dict(annotations or {}),
    )


__all__ = [
    "MAX_REF_DEPTH",
    "params_from_json_schema",
    "schema_warnings",
    "tool_from_function_schema",
    "type_from_json_schema",
]
