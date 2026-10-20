"""Canonicalisation and normalisation helpers.

The grader must not punish a model for writing ``"7"`` instead of ``7`` or
``{"b":1,"a":2}`` instead of ``{"a":2,"b":1}`` unless we explicitly ask it to.
Two grading strictnesses are supported everywhere:

``strict``
    Values must match after type-preserving canonicalisation only
    (dict key order and float formatting are still normalised, because those
    carry no information).

``normalized``
    Additionally coerces obvious cross-format artefacts: numeric strings to
    numbers, ``"true"``/``"yes"`` to booleans, case and whitespace folding on
    string values, single-element lists to scalars where the schema wants a
    scalar.

Every reported number states which strictness it used.

Case folding is not cosmetic. A model that answers ``borrower="Iris"`` where
the request said *borrower iris* has not made a semantic error, and — this is
the part that matters — capitalisation is something a **format** can induce.
A Go signature shows ``Borrower``, a title-cased table shows ``Iris``. If case
counted, the headline number would again be measuring the renderer rather than
the model, which is the same bug class that pinned seven formats at 0.0 when
tool names were compared literally. ``strict`` keeps case, and both are
reported side by side, so the effect of the decision stays visible.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from .types import ParamIR, ToolCall, ToolIR, TypeIR, TypeKind, canonical_name

_TRUE_WORDS = {"true", "yes", "y", "1", "on", "enabled"}
_FALSE_WORDS = {"false", "no", "n", "0", "off", "disabled"}
_NUM_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


def canonical_json(obj: Any) -> str:
    """Deterministic JSON string for hashing and equality."""
    return json.dumps(_canon(obj), sort_keys=True, separators=(",", ":"), default=str)


def _canon(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _canon(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, (list, tuple)):
        return [_canon(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return str(obj)
        # collapse 7.0 -> 7 so int/float rendering differences do not matter
        if obj == int(obj) and abs(obj) < 1e15:
            return int(obj)
        return round(obj, 9)
    return obj


def normalize_scalar(value: Any, want: TypeKind | None = None, *, fold_case: bool = False) -> Any:
    """Coerce a loosely-typed model value toward the schema's type.

    ``fold_case`` lowers string values. It is on at ``normalized`` strictness
    and off at ``strict``; see the module docstring for why.
    """
    if want is None:
        return _fold(value) if fold_case else value

    if want in (TypeKind.INTEGER, TypeKind.NUMBER):
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value) if want == TypeKind.INTEGER and float(value).is_integer() else value
        if isinstance(value, str):
            s = value.strip().replace(",", "").replace("_", "")
            if _NUM_RE.match(s):
                f = float(s)
                return int(f) if want == TypeKind.INTEGER and f.is_integer() else f
        return value

    if want == TypeKind.BOOLEAN:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            s = value.strip().lower()
            if s in _TRUE_WORDS:
                return True
            if s in _FALSE_WORDS:
                return False
        return value

    if want == TypeKind.STRING:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return _canon_num_str(value)
        if isinstance(value, str):
            s = value.strip()
            return s.casefold() if fold_case else s
        return value

    return _fold(value) if fold_case else value


def _fold(value: Any) -> Any:
    """Case-fold strings anywhere in a value, leaving everything else alone."""
    if isinstance(value, str):
        return value.strip().casefold()
    if isinstance(value, dict):
        return {k: _fold(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_fold(v) for v in value]
    return value


def _canon_num_str(v: float | int) -> str:
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


def normalize_value(value: Any, spec: TypeIR | None, *, fold_case: bool = False) -> Any:
    """Recursively normalise ``value`` against a :class:`TypeIR`."""
    if spec is None:
        return _canon(_fold(value) if fold_case else value)

    kind = spec.kind

    if kind == TypeKind.ANY:
        # A parameter typed `any` is how a production schema says "a string
        # or a list of them" (`email_smtp.to`: "Recipient address (str) or
        # list of addresses"). One recipient written as a one-element list is
        # the same call as the bare string, so the two collapse to one
        # canonical form. Without this, a model that always emits a list
        # fails every gold written as a string, and which shape a model
        # prefers varies with the output format: exactly the bias the real
        # arm exists to rule out. Typed arrays are left alone; there the
        # schema said list and a bare scalar is a real slip.
        if isinstance(value, (list, tuple)) and len(value) == 1 and not isinstance(value[0], (list, tuple, dict)):
            value = value[0]
        return _canon(_fold(value) if fold_case else value)

    if kind == TypeKind.ENUM:
        # Enums already match case-insensitively and return the declared
        # member, which is a better canonical form than a folded string.
        base = spec.base or TypeKind.STRING
        v = normalize_scalar(value, base)
        if isinstance(v, str):
            # case-insensitive enum matching against the declared members
            for member in spec.enum_values:
                if isinstance(member, str) and member.lower() == v.lower():
                    return member
        # A value that is not a declared member still has to compare the same
        # way every other string does, or two equally-invalid answers can
        # disagree on case alone.
        return _fold(v) if fold_case else v

    if kind == TypeKind.UNION:
        # try each branch, keep the first that changes nothing structurally
        for branch in spec.union_of:
            try:
                out = normalize_value(value, branch, fold_case=fold_case)
                if _type_matches(out, branch.kind):
                    return out
            except Exception:  # noqa: BLE001
                continue
        return _canon(_fold(value) if fold_case else value)

    if kind == TypeKind.ARRAY:
        if not isinstance(value, (list, tuple)):
            # a model writing "a, b" for a string array is a formatting slip
            if isinstance(value, str) and "," in value:
                value = [s.strip() for s in value.split(",")]
            else:
                value = [value]
        return [normalize_value(v, spec.item, fold_case=fold_case) for v in value]

    if kind == TypeKind.OBJECT:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except Exception:  # noqa: BLE001
                return _canon(_fold(value) if fold_case else value)
        if not isinstance(value, dict):
            return _canon(_fold(value) if fold_case else value)
        by_name = {f.name: f for f in spec.fields}
        by_canon = {canonical_name(f.name): f for f in spec.fields}
        out: dict[str, Any] = {}
        for k, v in value.items():
            f = by_name.get(k)
            key = k
            if f is None:
                # Same convention-insensitive match as at the top level:
                # `DeploymentDetails.OdometerKm` should reach `odometer_km`.
                f = by_canon.get(canonical_name(k))
                if f is not None:
                    key = f.name
            out[key] = normalize_value(v, f.type if f else None, fold_case=fold_case)
        return _canon(out)

    if isinstance(value, (list, dict)):
        return _canon(_fold(value) if fold_case else value)

    return normalize_scalar(value, kind, fold_case=fold_case)


def _type_matches(value: Any, kind: TypeKind) -> bool:
    checks = {
        TypeKind.STRING: lambda v: isinstance(v, str),
        TypeKind.INTEGER: lambda v: isinstance(v, int) and not isinstance(v, bool),
        TypeKind.NUMBER: lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        TypeKind.BOOLEAN: lambda v: isinstance(v, bool),
        TypeKind.ARRAY: lambda v: isinstance(v, (list, tuple)),
        TypeKind.OBJECT: lambda v: isinstance(v, dict),
        TypeKind.NULL: lambda v: v is None,
        TypeKind.ANY: lambda v: True,
    }
    return checks.get(kind, lambda v: True)(value)


def normalize_arguments(
    args: dict[str, Any],
    tool: ToolIR | None,
    *,
    strictness: str = "normalized",
    drop_defaulted_optionals: bool = True,
) -> dict[str, Any]:
    """Normalise a whole argument dict against a tool spec.

    ``drop_defaulted_optionals`` removes optional arguments whose supplied
    value equals the schema default — a model that spells out a default is
    not wrong, so we make gold and prediction comparable.
    """
    if not isinstance(args, dict):
        return {"_raw": args}

    if tool is None or strictness == "raw":
        return _canon(args)

    # Case folds at `normalized` only. `strict` returns above, before this.
    fold = strictness == "normalized"

    by_name = {p.name: p for p in tool.params}
    out: dict[str, Any] = {}
    for k, v in args.items():
        p: ParamIR | None = by_name.get(k)
        if strictness == "strict":
            out[k] = _canon(v)
            continue
        key = k
        if p is None:
            # The format may have shown the argument under another naming
            # convention — `StartHour` in Go, `startHour` in Swift. Map it back
            # to the schema name so it is compared, not counted as an invented
            # argument.
            p = tool.param(k)
            if p is not None:
                key = p.name
        out[key] = normalize_value(v, p.type if p else None, fold_case=fold)

    if drop_defaulted_optionals:
        for name, p in by_name.items():
            if name in out and not p.required and p.default is not None:
                if canonical_json(out[name]) == canonical_json(normalize_value(p.default, p.type, fold_case=fold)):
                    del out[name]
            # An optional argument given as null, "", {} or [] carries no
            # information: it is the model spelling out "not set", which
            # formats that list every optional field (typed signatures,
            # Go, Kotlin) invite it to do. Omitting it and writing null are
            # the same call, so they must grade the same (analysis 1).
            if name in out and not p.required and out[name] in (None, "", {}, []):
                del out[name]
    return out


def normalize_call(
    call: ToolCall,
    tool: ToolIR | None,
    *,
    strictness: str = "normalized",
) -> ToolCall:
    name = call.name.strip()
    if strictness != "strict":
        name = name.strip("`'\" \t\n").split("(")[0].strip()
        # tolerate namespaced names such as "functions.get_weather"
        if "." in name and tool is not None and name.endswith("." + tool.name):
            name = tool.name
    return ToolCall(
        name=name,
        arguments=normalize_arguments(call.arguments, tool, strictness=strictness),
        call_id=call.call_id,
    )


def calls_equal(
    a: ToolCall,
    b: ToolCall,
    tool: ToolIR | None = None,
    *,
    strictness: str = "normalized",
) -> bool:
    na = normalize_call(a, tool, strictness=strictness)
    nb = normalize_call(b, tool, strictness=strictness)
    if na.name != nb.name:
        return False
    return canonical_json(na.arguments) == canonical_json(nb.arguments)
