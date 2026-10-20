"""Canonical tool intermediate representation (IR).

Everything in ToolForm starts here. A tool is described exactly once, in this
IR, and every surface format (JSON Schema, YAML, TypeScript, prose, ...) is a
pure rendering of the same IR. That is what makes the format axis a clean
experiment: the semantics are provably identical across formats because they
come from one object.

Design rules:

* The IR is a plain dataclass tree with no dependency on any serializer.
* It is round-trippable: ``ToolIR.from_dict(t.to_dict()) == t``.
* It is expressive enough for every format we render (nesting, enums, unions,
  arrays of objects, optional/required, defaults, constraints) but small enough
  that a renderer for, say, a C header can still cover all of it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any


def canonical_name(name: str) -> str:
    """A name stripped of its naming convention.

    `calendar_find_v1`, `CalendarFindV1`, `calendarFindV1` and
    `calendar-find-v1` all collapse to `calendarfindv1`.

    Several formats rename on purpose, because that is what the language they
    imitate would do: Go exports `CalendarFindV1`, Java and Swift use
    `calendarFindV1`, and Swift also writes `startHour` for `start_hour`. A
    model that answers with the name the schema showed it has done exactly the
    right thing. Comparing against the raw IR name instead scored every such
    call as a hallucinated tool with unknown arguments, so eight formats sat at
    exactly 0.0 — a measurement of the renderer's naming convention, not of the
    model.
    """
    # A YAML or Python answer can carry a non-string key (`1: foo`); the
    # comparison is on the spelling, so it is folded like any other name
    # instead of crashing the grader.
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


class TypeKind(str, Enum):
    """The type system used across every rendered format."""

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"
    ENUM = "enum"
    UNION = "union"
    NULL = "null"
    ANY = "any"


#: Scalar kinds — used by renderers that cannot express structure.
SCALAR_KINDS = frozenset({TypeKind.STRING, TypeKind.INTEGER, TypeKind.NUMBER, TypeKind.BOOLEAN, TypeKind.NULL})


@dataclass(frozen=True)
class Constraints:
    """Value constraints attached to a type.

    Kept separate from :class:`TypeIR` so a renderer can drop all of them at
    once (the ``minified`` interface variants do exactly that).
    """

    minimum: float | int | None = None
    maximum: float | int | None = None
    min_length: int | None = None
    max_length: int | None = None
    min_items: int | None = None
    max_items: int | None = None
    pattern: str | None = None
    format: str | None = None  # e.g. "date", "email", "uri", "iso8601"

    def is_empty(self) -> bool:
        return all(getattr(self, f) is None for f in self.__dataclass_fields__)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Constraints":
        if not d:
            return cls()
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass(frozen=True)
class TypeIR:
    """A type in the tool IR.

    ``kind`` decides which of the optional slots are meaningful:

    ===========  =========================================================
    kind         meaningful slots
    ===========  =========================================================
    ARRAY        ``item``
    OBJECT       ``fields``
    ENUM         ``enum_values`` (plus ``base`` for the underlying scalar)
    UNION        ``union_of``
    scalars      ``constraints``
    ===========  =========================================================
    """

    kind: TypeKind = TypeKind.STRING
    item: "TypeIR | None" = None
    fields: tuple["ParamIR", ...] = ()
    enum_values: tuple[Any, ...] = ()
    union_of: tuple["TypeIR", ...] = ()
    base: TypeKind | None = None  # scalar backing an ENUM
    constraints: Constraints = field(default_factory=Constraints)

    # ---------------------------------------------------------------- helpers
    @property
    def is_scalar(self) -> bool:
        return self.kind in SCALAR_KINDS

    @property
    def depth(self) -> int:
        """Structural nesting depth. Scalars are 0."""
        if self.kind == TypeKind.ARRAY and self.item is not None:
            return 1 + self.item.depth
        if self.kind == TypeKind.OBJECT:
            return 1 + max((f.type.depth for f in self.fields), default=0)
        if self.kind == TypeKind.UNION and self.union_of:
            return max(t.depth for t in self.union_of)
        return 0

    def walk(self):
        """Yield every :class:`TypeIR` in this subtree, self first."""
        yield self
        if self.item is not None:
            yield from self.item.walk()
        for f in self.fields:
            yield from f.type.walk()
        for t in self.union_of:
            yield from t.walk()

    # ------------------------------------------------------------ constructors
    @classmethod
    def scalar(cls, kind: TypeKind, **constraints: Any) -> "TypeIR":
        return cls(kind=kind, constraints=Constraints(**constraints))

    @classmethod
    def string(cls, **c: Any) -> "TypeIR":
        return cls.scalar(TypeKind.STRING, **c)

    @classmethod
    def integer(cls, **c: Any) -> "TypeIR":
        return cls.scalar(TypeKind.INTEGER, **c)

    @classmethod
    def number(cls, **c: Any) -> "TypeIR":
        return cls.scalar(TypeKind.NUMBER, **c)

    @classmethod
    def boolean(cls) -> "TypeIR":
        return cls(kind=TypeKind.BOOLEAN)

    @classmethod
    def array_of(cls, item: "TypeIR", **c: Any) -> "TypeIR":
        return cls(kind=TypeKind.ARRAY, item=item, constraints=Constraints(**c))

    @classmethod
    def object_of(cls, fields: "list[ParamIR] | tuple[ParamIR, ...]") -> "TypeIR":
        return cls(kind=TypeKind.OBJECT, fields=tuple(fields))

    @classmethod
    def enum_of(cls, values: list[Any], base: TypeKind = TypeKind.STRING) -> "TypeIR":
        return cls(kind=TypeKind.ENUM, enum_values=tuple(values), base=base)

    @classmethod
    def union_of_types(cls, types: "list[TypeIR]") -> "TypeIR":
        return cls(kind=TypeKind.UNION, union_of=tuple(types))

    # ------------------------------------------------------------- (de)serial
    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind.value}
        if self.item is not None:
            d["item"] = self.item.to_dict()
        if self.fields:
            d["fields"] = [f.to_dict() for f in self.fields]
        if self.enum_values:
            d["enum_values"] = list(self.enum_values)
        if self.union_of:
            d["union_of"] = [t.to_dict() for t in self.union_of]
        if self.base is not None:
            d["base"] = self.base.value
        if not self.constraints.is_empty():
            d["constraints"] = self.constraints.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TypeIR":
        return cls(
            kind=TypeKind(d.get("kind", "string")),
            item=cls.from_dict(d["item"]) if d.get("item") else None,
            fields=tuple(ParamIR.from_dict(f) for f in d.get("fields", [])),
            enum_values=tuple(d.get("enum_values", [])),
            union_of=tuple(cls.from_dict(t) for t in d.get("union_of", [])),
            base=TypeKind(d["base"]) if d.get("base") else None,
            constraints=Constraints.from_dict(d.get("constraints")),
        )


@dataclass(frozen=True)
class ParamIR:
    """One parameter of a tool (or one field of an object type)."""

    name: str
    type: TypeIR = field(default_factory=TypeIR)
    description: str = ""
    required: bool = True
    default: Any = None
    example: Any = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "type": self.type.to_dict(),
            "required": self.required,
        }
        if self.description:
            d["description"] = self.description
        if self.default is not None:
            d["default"] = self.default
        if self.example is not None:
            d["example"] = self.example
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ParamIR":
        return cls(
            name=d["name"],
            type=TypeIR.from_dict(d.get("type", {})),
            description=d.get("description", ""),
            required=bool(d.get("required", True)),
            default=d.get("default"),
            example=d.get("example"),
        )


@dataclass(frozen=True)
class ToolIR:
    """A single tool: name, prose description, typed parameters, return type.

    ``kernel`` and ``kernel_args`` connect the tool to its executable
    simulator. Real-world tools use the same fields, so the grader
    does not care whether a tool is synthetic or real.
    """

    name: str
    description: str = ""
    params: tuple[ParamIR, ...] = ()
    returns: TypeIR | None = None
    returns_description: str = ""
    examples: tuple[dict[str, Any], ...] = ()
    domain: str = "generic"
    category: str = "generic"
    tags: tuple[str, ...] = ()
    kernel: str | None = None
    kernel_args: dict[str, Any] = field(default_factory=dict)
    origin: str = "synthetic"  # "synthetic" | "real"
    # Deployment metadata that is not part of the schema: a policy attached
    # to the tool ("disabled this session", "needs confirmation"). Renderers
    # never read it directly; `RenderOptions.apply_to` folds `policy_text`
    # into the description when the cell asks for that placement. (novel)
    annotations: dict[str, Any] = field(default_factory=dict)

    # ----------------------------------------------------------------- access
    @property
    def required_params(self) -> tuple[ParamIR, ...]:
        return tuple(p for p in self.params if p.required)

    @property
    def optional_params(self) -> tuple[ParamIR, ...]:
        return tuple(p for p in self.params if not p.required)

    def param(self, name: str) -> ParamIR | None:
        for p in self.params:
            if p.name == name:
                return p
        # Fall back to the naming convention the format used. A Go or Swift
        # rendering shows `StartHour` / `startHour` for `start_hour`, and a
        # model answering with the name it was shown is not making a mistake.
        key = canonical_name(name)
        for p in self.params:
            if canonical_name(p.name) == key:
                return p
        return None

    # ------------------------------------------------------------- complexity
    @property
    def max_depth(self) -> int:
        return max((p.type.depth for p in self.params), default=0)

    @property
    def n_enums(self) -> int:
        return sum(1 for p in self.params for t in p.type.walk() if t.kind == TypeKind.ENUM)

    @property
    def n_unions(self) -> int:
        return sum(1 for p in self.params for t in p.type.walk() if t.kind == TypeKind.UNION)

    def complexity_vector(self) -> dict[str, int]:
        """Numeric complexity features, used as regressors in the law fits."""
        return {
            "n_params": len(self.params),
            "n_required": len(self.required_params),
            "n_optional": len(self.optional_params),
            "max_depth": self.max_depth,
            "n_enums": self.n_enums,
            "n_unions": self.n_unions,
            "n_arrays": sum(1 for p in self.params for t in p.type.walk() if t.kind == TypeKind.ARRAY),
            "n_objects": sum(1 for p in self.params for t in p.type.walk() if t.kind == TypeKind.OBJECT),
            "desc_chars": len(self.description) + sum(len(p.description) for p in self.params),
        }

    # -------------------------------------------------------------- transform
    def without_descriptions(self) -> "ToolIR":
        """Strip every prose description (the ``descriptions=off`` ablation)."""
        return replace(
            self,
            description="",
            returns_description="",
            params=tuple(_strip_param_desc(p) for p in self.params),
            examples=(),
        )

    def without_constraints(self) -> "ToolIR":
        """Strip value constraints (used by the ``minified`` variants)."""
        return replace(self, params=tuple(_strip_param_constraints(p) for p in self.params))

    def without_defaults(self) -> "ToolIR":
        """Strip default values and examples."""
        return replace(self, params=tuple(_strip_param_defaults(p) for p in self.params))

    # ------------------------------------------------------------- (de)serial
    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "params": [p.to_dict() for p in self.params],
            "domain": self.domain,
            "category": self.category,
            "origin": self.origin,
        }
        if self.returns is not None:
            d["returns"] = self.returns.to_dict()
        if self.returns_description:
            d["returns_description"] = self.returns_description
        if self.examples:
            d["examples"] = [dict(e) for e in self.examples]
        if self.tags:
            d["tags"] = list(self.tags)
        if self.kernel:
            d["kernel"] = self.kernel
        if self.kernel_args:
            d["kernel_args"] = dict(self.kernel_args)
        if self.annotations:
            d["annotations"] = dict(self.annotations)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ToolIR":
        return cls(
            name=d["name"],
            description=d.get("description", ""),
            params=tuple(ParamIR.from_dict(p) for p in d.get("params", [])),
            returns=TypeIR.from_dict(d["returns"]) if d.get("returns") else None,
            returns_description=d.get("returns_description", ""),
            examples=tuple(d.get("examples", [])),
            domain=d.get("domain", "generic"),
            category=d.get("category", "generic"),
            tags=tuple(d.get("tags", [])),
            kernel=d.get("kernel"),
            kernel_args=dict(d.get("kernel_args", {})),
            origin=d.get("origin", "synthetic"),
            annotations=dict(d.get("annotations", {})),
        )

    def fingerprint(self) -> str:
        """Stable hash of the semantic content (used for contamination checks)."""
        payload = json.dumps(self.to_dict(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def interface_key(self) -> str:
        """Everything a model can see of the tool except its name.

        Two tools with the same key are indistinguishable from the prompt:
        same description, same parameters, same return type. The generator
        makes such twins when a variant's rotation of optional fields cycles
        back onto another variant,
        and the grader treats a call to either as a call to the gold
        (``ToolUniverse.equivalence_classes``).
        """
        payload = {
            "description": self.description,
            "params": [p.to_dict() for p in self.params],
            "returns": self.returns.to_dict() if self.returns is not None else None,
            "returns_description": self.returns_description,
            "annotations": self.annotations,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _strip_param_defaults(p: ParamIR) -> ParamIR:
    t = p.type
    if t.fields:
        t = replace(t, fields=tuple(_strip_param_defaults(f) for f in t.fields))
    return replace(p, default=None, example=None, type=t)


def _strip_param_desc(p: ParamIR) -> ParamIR:
    return replace(p, description="", example=None, type=_strip_type_desc(p.type))


def _strip_type_desc(t: TypeIR) -> TypeIR:
    return replace(
        t,
        item=_strip_type_desc(t.item) if t.item else None,
        fields=tuple(_strip_param_desc(f) for f in t.fields),
        union_of=tuple(_strip_type_desc(u) for u in t.union_of),
    )


def _strip_param_constraints(p: ParamIR) -> ParamIR:
    return replace(p, type=_strip_type_constraints(p.type))


def _strip_type_constraints(t: TypeIR) -> TypeIR:
    return replace(
        t,
        constraints=Constraints(),
        item=_strip_type_constraints(t.item) if t.item else None,
        fields=tuple(_strip_param_constraints(f) for f in t.fields),
        union_of=tuple(_strip_type_constraints(u) for u in t.union_of),
    )


_RENDERED_SUFFIXES = ("request", "input", "args", "params", "call", "message", "msg")


@dataclass
class ToolUniverse:
    """An ordered collection of tools presented to the model in one context."""

    tools: list[ToolIR] = field(default_factory=list)
    universe_id: str = "universe"
    seed: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.tools)

    def __iter__(self):
        return iter(self.tools)

    def __getitem__(self, i):
        return self.tools[i]

    def names(self) -> list[str]:
        return [t.name for t in self.tools]

    def get(self, name: str) -> ToolIR | None:
        for t in self.tools:
            if t.name == name:
                return t
        # Resolve across naming conventions. Several formats deliberately
        # rename: Go renders `CalendarFindV1`, Java and Swift `calendarFindV1`,
        # for an IR name of `calendar_find_v1`. A model that answers with the
        # name the schema showed it is right, and scoring that as a
        # hallucinated tool measures the renderer, not the model. Only an
        # existing tool can be matched, so inventing one still counts as a
        # hallucination.
        key = canonical_name(name)
        if not key:
            return None
        for t in self.tools:
            if canonical_name(t.name) == key:
                return t
        # Several renderers name a tool's message or rule after the tool with
        # a suffix, because the language they imitate has no bare function:
        # Avro, FlatBuffers and Protobuf write `DevopsDeployV2Request`,
        # Smithy `...Input`, a dataclass rendering `...Args`, a grammar
        # `devops_deploy_v2_call`. A model that answers with that name has
        # named the tool it was shown. Unique matches only.
        for suffix in _RENDERED_SUFFIXES:
            if key.endswith(suffix) and len(key) > len(suffix):
                bare = key[: -len(suffix)]
                hits = [t for t in self.tools if canonical_name(t.name) == bare]
                if len(hits) == 1:
                    return hits[0]
        return None

    def subset(self, n: int) -> "ToolUniverse":
        return ToolUniverse(
            tools=self.tools[:n],
            universe_id=f"{self.universe_id}:n{n}",
            seed=self.seed,
            meta=dict(self.meta),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "universe_id": self.universe_id,
            "seed": self.seed,
            "meta": self.meta,
            "tools": [t.to_dict() for t in self.tools],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ToolUniverse":
        return cls(
            tools=[ToolIR.from_dict(t) for t in d.get("tools", [])],
            universe_id=d.get("universe_id", "universe"),
            seed=d.get("seed"),
            meta=dict(d.get("meta", {})),
        )

    def fingerprint(self) -> str:
        h = hashlib.sha256()
        for t in self.tools:
            h.update(t.fingerprint().encode())
        return h.hexdigest()[:16]

    def equivalence_classes(self) -> dict[str, frozenset[str]]:
        """Tool name -> the names of every displayed tool it cannot be told
        apart from (itself included), by :meth:`ToolIR.interface_key`.

        Cached on the universe; recomputed when its tool names change. A tool
        with no twin maps to a singleton, so a caller can always look a name
        up.
        """
        names = tuple(t.name for t in self.tools)
        cache = self.__dict__.get("_eq_cache")
        if cache is not None and cache[0] == names:
            return cache[1]
        # A pressure treatment appends a sentence to one tool's description
        # (adversarial._with_tool). That sentence must not break the tool's
        # twinship: the request cannot tell the twins apart before or after
        # it, and a call to the twin graded correct in the control arm was
        # graded wrong in the treated arm. The treatment
        # records the untreated key in the universe's meta; use it here.
        untreated = self.meta.get("untreated_keys") or {}
        groups: dict[str, list[str]] = {}
        for t in self.tools:
            groups.setdefault(untreated.get(t.name) or t.interface_key(), []).append(t.name)
        classes = {name: frozenset(members) for members in groups.values() for name in members}
        self.__dict__["_eq_cache"] = (names, classes)
        return classes


@dataclass(frozen=True)
class ToolCall:
    """A single (tool, arguments) pair — the unit the grader compares."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    call_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {"name": self.name, "arguments": self.arguments}
        if self.call_id:
            d["call_id"] = self.call_id
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ToolCall":
        args = d.get("arguments", d.get("args", d.get("parameters", {}))) or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:  # noqa: BLE001
                args = {"_raw": args}
        return cls(
            name=d.get("name", d.get("tool", d.get("function", ""))),
            arguments=args if isinstance(args, dict) else {"_raw": args},
            call_id=d.get("call_id") or d.get("id"),
        )

    def __str__(self) -> str:
        return f"{self.name}({json.dumps(self.arguments, sort_keys=True, default=str)})"
