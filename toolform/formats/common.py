"""Shared conversions used by many renderers.

Two things live here:

1. ``to_json_schema`` — the IR expressed as JSON Schema. Half the formats in
   the study are dialects or serialisations of JSON Schema, so they all go
   through this one function and are therefore guaranteed consistent.
2. ``LANG_TYPES`` — how each scalar kind is spelled in each target language,
   plus generic constructors for arrays/objects/enums/unions. Adding a new
   source-language format is then a few lines, not a new type system.
"""

from __future__ import annotations

from typing import Any, Callable

from ..ir import ParamIR, ToolIR, TypeIR, TypeKind

# --------------------------------------------------------------------------- #
# JSON Schema
# --------------------------------------------------------------------------- #


def type_to_json_schema(t: TypeIR, *, descriptions: bool = True) -> dict[str, Any]:
    """Convert one :class:`TypeIR` into a JSON Schema fragment."""
    k = t.kind

    if k == TypeKind.ENUM:
        base = (t.base or TypeKind.STRING).value
        base = "number" if base == "number" else base
        out: dict[str, Any] = {"type": base, "enum": list(t.enum_values)}
    elif k == TypeKind.UNION:
        out = {"anyOf": [type_to_json_schema(u, descriptions=descriptions) for u in t.union_of]}
    elif k == TypeKind.ARRAY:
        out = {"type": "array"}
        if t.item is not None:
            out["items"] = type_to_json_schema(t.item, descriptions=descriptions)
    elif k == TypeKind.OBJECT:
        props: dict[str, Any] = {}
        required: list[str] = []
        for f in t.fields:
            props[f.name] = param_to_json_schema(f, descriptions=descriptions)
            if f.required:
                required.append(f.name)
        out = {"type": "object", "properties": props}
        if required:
            out["required"] = required
    elif k == TypeKind.ANY:
        out = {}
    elif k == TypeKind.NULL:
        out = {"type": "null"}
    else:
        out = {"type": k.value}

    c = t.constraints
    if c.minimum is not None:
        out["minimum"] = c.minimum
    if c.maximum is not None:
        out["maximum"] = c.maximum
    if c.min_length is not None:
        out["minLength"] = c.min_length
    if c.max_length is not None:
        out["maxLength"] = c.max_length
    if c.min_items is not None:
        out["minItems"] = c.min_items
    if c.max_items is not None:
        out["maxItems"] = c.max_items
    if c.pattern:
        out["pattern"] = c.pattern
    if c.format:
        out["format"] = c.format
    return out


def param_to_json_schema(p: ParamIR, *, descriptions: bool = True) -> dict[str, Any]:
    out = type_to_json_schema(p.type, descriptions=descriptions)
    if descriptions and p.description:
        out["description"] = p.description
    if p.default is not None:
        out["default"] = p.default
    return out


def tool_to_json_schema(
    tool: ToolIR,
    *,
    style: str = "openai",
    descriptions: bool = True,
    include_returns: bool = True,
) -> dict[str, Any]:
    """Render a tool as JSON Schema in one of the vendor shapes.

    ``style``:
      ``openai``     -> ``{"type":"function","function":{...,"parameters":{...}}}``
      ``openai_flat``-> ``{"name":..,"description":..,"parameters":{...}}``
      ``anthropic``  -> ``{"name":..,"description":..,"input_schema":{...}}``
      ``plain``      -> ``{"name":..,"description":..,"parameters":{...}}`` (alias of flat)
    """
    props: dict[str, Any] = {}
    required: list[str] = []
    for p in tool.params:
        props[p.name] = param_to_json_schema(p, descriptions=descriptions)
        if p.required:
            required.append(p.name)

    params_schema: dict[str, Any] = {
        "type": "object",
        "properties": props,
    }
    if required:
        params_schema["required"] = required

    body: dict[str, Any] = {"name": tool.name}
    if descriptions and tool.description:
        body["description"] = tool.description

    if style == "anthropic":
        body["input_schema"] = params_schema
    else:
        body["parameters"] = params_schema

    if include_returns and tool.returns is not None:
        rs = type_to_json_schema(tool.returns, descriptions=descriptions)
        if descriptions and tool.returns_description:
            rs["description"] = tool.returns_description
        body["returns"] = rs

    if style == "openai":
        return {"type": "function", "function": body}
    return body


# --------------------------------------------------------------------------- #
# language type spellings
# --------------------------------------------------------------------------- #


class LangSpec:
    """How one target language spells the IR's types."""

    def __init__(
        self,
        name: str,
        scalars: dict[TypeKind, str],
        array: Callable[[str], str],
        obj: str = "object",
        any_type: str = "any",
        null_type: str = "null",
        optional: Callable[[str], str] | None = None,
        union: Callable[[list[str]], str] | None = None,
        enum_literal: Callable[[Any], str] | None = None,
        enum: Callable[[list[str]], str] | None = None,
    ) -> None:
        self.name = name
        self.scalars = scalars
        self.array = array
        self.obj = obj
        self.any_type = any_type
        self.null_type = null_type
        self.optional = optional or (lambda s: f"{s} | null")
        self.union = union or (lambda parts: " | ".join(parts))
        self.enum_literal = enum_literal or _default_enum_literal
        self.enum = enum or (lambda members: " | ".join(members))

    def render(self, t: TypeIR, *, obj_name: str | None = None) -> str:
        k = t.kind
        if k == TypeKind.ARRAY:
            inner = self.render(t.item) if t.item is not None else self.any_type
            return self.array(inner)
        if k == TypeKind.OBJECT:
            return obj_name or self.obj
        if k == TypeKind.ENUM:
            return self.enum([self.enum_literal(v) for v in t.enum_values])
        if k == TypeKind.UNION:
            return self.union([self.render(u) for u in t.union_of])
        if k == TypeKind.ANY:
            return self.any_type
        if k == TypeKind.NULL:
            return self.null_type
        return self.scalars.get(k, self.any_type)


def _default_enum_literal(v: Any) -> str:
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _lit_single(v: Any) -> str:
    if isinstance(v, str):
        return f"'{v}'"
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


S = TypeKind

LANG_TYPES: dict[str, LangSpec] = {
    "typescript": LangSpec(
        "typescript",
        {S.STRING: "string", S.INTEGER: "number", S.NUMBER: "number", S.BOOLEAN: "boolean"},
        lambda inner: f"{inner}[]",
        obj="Record<string, unknown>",
        any_type="unknown",
        null_type="null",
    ),
    "python": LangSpec(
        "python",
        {S.STRING: "str", S.INTEGER: "int", S.NUMBER: "float", S.BOOLEAN: "bool"},
        lambda inner: f"list[{inner}]",
        obj="dict[str, Any]",
        any_type="Any",
        null_type="None",
        optional=lambda s: f"Optional[{s}]",
        union=lambda parts: " | ".join(parts),
        enum=lambda members: f"Literal[{', '.join(members)}]",
    ),
    "go": LangSpec(
        "go",
        {S.STRING: "string", S.INTEGER: "int", S.NUMBER: "float64", S.BOOLEAN: "bool"},
        lambda inner: f"[]{inner}",
        obj="map[string]interface{}",
        any_type="interface{}",
        null_type="nil",
        union=lambda parts: "interface{}",
        enum=lambda members: "string",
    ),
    "rust": LangSpec(
        "rust",
        {S.STRING: "String", S.INTEGER: "i64", S.NUMBER: "f64", S.BOOLEAN: "bool"},
        lambda inner: f"Vec<{inner}>",
        obj="serde_json::Value",
        any_type="serde_json::Value",
        null_type="()",
        optional=lambda s: f"Option<{s}>",
        union=lambda parts: "serde_json::Value",
        enum=lambda members: "String",
    ),
    "java": LangSpec(
        "java",
        {S.STRING: "String", S.INTEGER: "int", S.NUMBER: "double", S.BOOLEAN: "boolean"},
        lambda inner: f"List<{inner}>",
        obj="Map<String, Object>",
        any_type="Object",
        null_type="void",
        optional=lambda s: f"Optional<{s}>",
        union=lambda parts: "Object",
        enum=lambda members: "String",
    ),
    "kotlin": LangSpec(
        "kotlin",
        {S.STRING: "String", S.INTEGER: "Int", S.NUMBER: "Double", S.BOOLEAN: "Boolean"},
        lambda inner: f"List<{inner}>",
        obj="Map<String, Any>",
        any_type="Any",
        null_type="Unit",
        optional=lambda s: f"{s}?",
        union=lambda parts: "Any",
        enum=lambda members: "String",
    ),
    "swift": LangSpec(
        "swift",
        {S.STRING: "String", S.INTEGER: "Int", S.NUMBER: "Double", S.BOOLEAN: "Bool"},
        lambda inner: f"[{inner}]",
        obj="[String: Any]",
        any_type="Any",
        null_type="Void",
        optional=lambda s: f"{s}?",
        union=lambda parts: "Any",
        enum=lambda members: "String",
    ),
    "csharp": LangSpec(
        "csharp",
        {S.STRING: "string", S.INTEGER: "int", S.NUMBER: "double", S.BOOLEAN: "bool"},
        lambda inner: f"List<{inner}>",
        obj="Dictionary<string, object>",
        any_type="object",
        null_type="void",
        optional=lambda s: f"{s}?",
        union=lambda parts: "object",
        enum=lambda members: "string",
    ),
    "c": LangSpec(
        "c",
        {S.STRING: "const char*", S.INTEGER: "int", S.NUMBER: "double", S.BOOLEAN: "bool"},
        lambda inner: f"{inner}*",
        obj="json_t*",
        any_type="void*",
        null_type="void",
        optional=lambda s: s,
        union=lambda parts: "void*",
        enum=lambda members: "const char*",
    ),
    "cpp": LangSpec(
        "cpp",
        {S.STRING: "std::string", S.INTEGER: "int64_t", S.NUMBER: "double", S.BOOLEAN: "bool"},
        lambda inner: f"std::vector<{inner}>",
        obj="nlohmann::json",
        any_type="std::any",
        null_type="void",
        optional=lambda s: f"std::optional<{s}>",
        union=lambda parts: f"std::variant<{', '.join(parts)}>",
        enum=lambda members: "std::string",
    ),
    "haskell": LangSpec(
        "haskell",
        {S.STRING: "Text", S.INTEGER: "Int", S.NUMBER: "Double", S.BOOLEAN: "Bool"},
        lambda inner: f"[{inner}]",
        obj="Object",
        any_type="Value",
        null_type="()",
        optional=lambda s: f"Maybe {s}",
        union=lambda parts: f"Either {' '.join(parts)}",
        enum=lambda members: "Text",
    ),
    "ocaml": LangSpec(
        "ocaml",
        {S.STRING: "string", S.INTEGER: "int", S.NUMBER: "float", S.BOOLEAN: "bool"},
        lambda inner: f"{inner} list",
        obj="Yojson.Safe.t",
        any_type="Yojson.Safe.t",
        null_type="unit",
        optional=lambda s: f"{s} option",
        union=lambda parts: "Yojson.Safe.t",
        enum=lambda members: "string",
    ),
    "scala": LangSpec(
        "scala",
        {S.STRING: "String", S.INTEGER: "Int", S.NUMBER: "Double", S.BOOLEAN: "Boolean"},
        lambda inner: f"Seq[{inner}]",
        obj="Map[String, Any]",
        any_type="Any",
        null_type="Unit",
        optional=lambda s: f"Option[{s}]",
        union=lambda parts: " | ".join(parts),
        enum=lambda members: "String",
    ),
    "ruby": LangSpec(
        "ruby",
        {S.STRING: "String", S.INTEGER: "Integer", S.NUMBER: "Float", S.BOOLEAN: "Boolean"},
        lambda inner: f"Array[{inner}]",
        obj="Hash",
        any_type="Object",
        null_type="nil",
        optional=lambda s: f"{s}?",
        union=lambda parts: " | ".join(parts),
        enum=lambda members: "String",
    ),
    "php": LangSpec(
        "php",
        {S.STRING: "string", S.INTEGER: "int", S.NUMBER: "float", S.BOOLEAN: "bool"},
        lambda inner: "array",
        obj="array",
        any_type="mixed",
        null_type="void",
        optional=lambda s: f"?{s}",
        union=lambda parts: "|".join(parts),
        enum=lambda members: "string",
    ),
    "lua": LangSpec(
        "lua",
        {S.STRING: "string", S.INTEGER: "number", S.NUMBER: "number", S.BOOLEAN: "boolean"},
        lambda inner: "table",
        obj="table",
        any_type="any",
        null_type="nil",
        optional=lambda s: f"{s}?",
        union=lambda parts: "|".join(parts),
        enum=lambda members: "string",
    ),
    "zig": LangSpec(
        "zig",
        {S.STRING: "[]const u8", S.INTEGER: "i64", S.NUMBER: "f64", S.BOOLEAN: "bool"},
        lambda inner: f"[]{inner}",
        obj="std.json.Value",
        any_type="anytype",
        null_type="void",
        optional=lambda s: f"?{s}",
        union=lambda parts: "std.json.Value",
        enum=lambda members: "[]const u8",
    ),
    "elixir": LangSpec(
        "elixir",
        {S.STRING: "String.t()", S.INTEGER: "integer()", S.NUMBER: "float()", S.BOOLEAN: "boolean()"},
        lambda inner: f"[{inner}]",
        obj="map()",
        any_type="any()",
        null_type="nil",
        optional=lambda s: f"{s} | nil",
        union=lambda parts: " | ".join(parts),
        enum=lambda members: " | ".join(members),
    ),
    "julia": LangSpec(
        "julia",
        {S.STRING: "String", S.INTEGER: "Int", S.NUMBER: "Float64", S.BOOLEAN: "Bool"},
        lambda inner: f"Vector{{{inner}}}",
        obj="Dict{String,Any}",
        any_type="Any",
        null_type="Nothing",
        optional=lambda s: f"Union{{{s},Nothing}}",
        union=lambda parts: f"Union{{{','.join(parts)}}}",
        enum=lambda members: "String",
    ),
    "r": LangSpec(
        "r",
        {S.STRING: "character", S.INTEGER: "integer", S.NUMBER: "numeric", S.BOOLEAN: "logical"},
        lambda inner: f"list({inner})",
        obj="list",
        any_type="ANY",
        null_type="NULL",
        optional=lambda s: s,
        union=lambda parts: "ANY",
        enum=lambda members: "character",
    ),
    "sql": LangSpec(
        "sql",
        {S.STRING: "TEXT", S.INTEGER: "INTEGER", S.NUMBER: "DOUBLE PRECISION", S.BOOLEAN: "BOOLEAN"},
        lambda inner: f"{inner}[]",
        obj="JSONB",
        any_type="JSONB",
        null_type="NULL",
        optional=lambda s: s,
        union=lambda parts: "JSONB",
        enum=lambda members: "TEXT",
    ),
    "graphql": LangSpec(
        "graphql",
        {S.STRING: "String", S.INTEGER: "Int", S.NUMBER: "Float", S.BOOLEAN: "Boolean"},
        lambda inner: f"[{inner}]",
        obj="JSON",
        any_type="JSON",
        null_type="JSON",
        optional=lambda s: s,
        union=lambda parts: "JSON",
        enum=lambda members: "String",
    ),
    "protobuf": LangSpec(
        "protobuf",
        {S.STRING: "string", S.INTEGER: "int64", S.NUMBER: "double", S.BOOLEAN: "bool"},
        lambda inner: f"repeated {inner}",
        obj="google.protobuf.Struct",
        any_type="google.protobuf.Any",
        null_type="google.protobuf.NullValue",
        optional=lambda s: f"optional {s}",
        union=lambda parts: "google.protobuf.Any",
        enum=lambda members: "string",
    ),
    "thrift": LangSpec(
        "thrift",
        {S.STRING: "string", S.INTEGER: "i64", S.NUMBER: "double", S.BOOLEAN: "bool"},
        lambda inner: f"list<{inner}>",
        obj="map<string,string>",
        any_type="string",
        null_type="void",
        optional=lambda s: s,
        union=lambda parts: "string",
        enum=lambda members: "string",
    ),
    "avro": LangSpec(
        "avro",
        {S.STRING: "string", S.INTEGER: "long", S.NUMBER: "double", S.BOOLEAN: "boolean"},
        lambda inner: f"array<{inner}>",
        obj="map<string,string>",
        any_type="bytes",
        null_type="null",
        optional=lambda s: f"union {{ null, {s} }}",
        union=lambda parts: f"union {{ {', '.join(parts)} }}",
        enum=lambda members: "string",
    ),
    "wit": LangSpec(
        "wit",
        {S.STRING: "string", S.INTEGER: "s64", S.NUMBER: "float64", S.BOOLEAN: "bool"},
        lambda inner: f"list<{inner}>",
        obj="string",
        any_type="string",
        null_type="unit",
        optional=lambda s: f"option<{s}>",
        union=lambda parts: f"variant {{ {', '.join(parts)} }}",
        enum=lambda members: "string",
    ),
    "cue": LangSpec(
        "cue",
        {S.STRING: "string", S.INTEGER: "int", S.NUMBER: "number", S.BOOLEAN: "bool"},
        lambda inner: f"[...{inner}]",
        obj="{...}",
        any_type="_",
        null_type="null",
        optional=lambda s: f"{s} | *null",
        union=lambda parts: " | ".join(parts),
    ),
}


def lang(name: str) -> LangSpec:
    return LANG_TYPES[name]


def render_type(t: TypeIR, language: str, *, obj_name: str | None = None) -> str:
    return LANG_TYPES[language].render(t, obj_name=obj_name)


def collect_object_types(tool: ToolIR) -> list[tuple[str, TypeIR]]:
    """Find every nested OBJECT type in a tool, with a generated type name.

    Languages that need named struct/interface declarations (TypeScript, Go,
    Rust, protobuf, ...) use this so that nesting is expressed properly rather
    than flattened away — nesting depth is one of our experimental axes, so
    losing it would break the comparison.
    """
    found: list[tuple[str, TypeIR]] = []
    seen: set[int] = set()

    def visit(t: TypeIR, path: str) -> None:
        if id(t) in seen:
            return
        seen.add(id(t))
        if t.kind == TypeKind.OBJECT and t.fields:
            found.append((path, t))
            for f in t.fields:
                visit(f.type, path + _pascal(f.name))
        elif t.kind == TypeKind.ARRAY and t.item is not None:
            visit(t.item, path + "Item")
        elif t.kind == TypeKind.UNION:
            for i, u in enumerate(t.union_of):
                visit(u, f"{path}Alt{i + 1}")

    for p in tool.params:
        visit(p.type, _pascal(tool.name) + _pascal(p.name))
    return found


def object_type_name(tool: ToolIR, param: ParamIR) -> str:
    return _pascal(tool.name) + _pascal(param.name)


def _pascal(s: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in s.replace("-", "_").split("_") if part)


def pascal(s: str) -> str:
    return _pascal(s)


def camel(s: str) -> str:
    p = _pascal(s)
    return p[:1].lower() + p[1:] if p else s


def kebab(s: str) -> str:
    return s.replace("_", "-")


def render_type_named(t: TypeIR, language: str, tool: ToolIR, param: ParamIR) -> str:
    """Type spelling that uses a generated struct name for object types."""
    spec = LANG_TYPES[language]
    if t.kind == TypeKind.OBJECT and t.fields:
        return object_type_name(tool, param)
    if t.kind == TypeKind.ARRAY and t.item is not None and t.item.kind == TypeKind.OBJECT:
        return spec.array(object_type_name(tool, param) + "Item")
    return spec.render(t)


def ordered_params(tool: ToolIR) -> list[ParamIR]:
    """Required parameters first, then optional ones, order preserved within each.

    Only used by source-language renderers, where an optional argument with a
    default cannot legally precede a required one. Declaration order is
    otherwise held constant across formats, and the position ablation varies it
    deliberately.
    """
    return [p for p in tool.params if p.required] + [p for p in tool.params if not p.required]


def py_value(v: Any) -> str:
    """Python literal for a default value."""
    if v is None:
        return "None"
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, (list, dict)):
        import json as _json

        return _json.dumps(v)
    return str(v)


def js_value(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, (list, dict)):
        import json as _json

        return _json.dumps(v)
    return str(v)
