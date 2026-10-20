"""Interface definition languages.

IDLs are the closest existing thing to "a schema for a remote call", which is
exactly what a tool is. They are also machine-generated far more often than
hand-written, so they test whether a model benefits from a format it has seen
mostly as generated code.
"""

from __future__ import annotations

import json

from ..ir import ParamIR, ToolIR, TypeIR, TypeKind
from .base import FormatMeta, RenderOptions, SchemaRenderer, register
from .common import camel, lang, pascal


def _field_docs(p: ParamIR, opts: RenderOptions, comment: str = "//") -> list[str]:
    if opts.descriptions and p.description:
        return [f"  {comment} {p.description}"]
    return []


@register
class ProtobufIDL(SchemaRenderer):
    meta = FormatMeta(
        id="protobuf",
        name="Protocol Buffers service definition",
        family="idl",
        description=(
            "A `service` with one rpc per tool and a request message per tool. "
            "Field numbers, `optional`, and nested messages carry the whole "
            "schema."
        ),
        default_protocol="json_object",
        real_world_origin="Protocol Buffers 3 / gRPC",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        spec = lang("protobuf")
        out: list[str] = ['syntax = "proto3";', "", "package tools;", ""]
        for t in tools:
            msg = pascal(t.name) + "Request"
            # nested enums first
            for p in t.params:
                if p.type.kind == TypeKind.ENUM:
                    ename = pascal(t.name) + pascal(p.name)
                    out.append(f"enum {ename} {{")
                    for i, v in enumerate(p.type.enum_values):
                        out.append(f"  {_enum_const(v)} = {i};")
                    out.append("}")
                    out.append("")
            if opts.descriptions and t.description:
                out.append(f"// {t.description}")
            out.append(f"message {msg} {{")
            for i, p in enumerate(t.params, start=1):
                out.extend(_field_docs(p, opts))
                if p.type.kind == TypeKind.ENUM:
                    ty = pascal(t.name) + pascal(p.name)
                elif p.type.kind == TypeKind.OBJECT:
                    ty = "google.protobuf.Struct"
                else:
                    ty = spec.render(p.type)
                prefix = "" if p.required or ty.startswith("repeated") else "optional "
                out.append(f"  {prefix}{ty} {p.name} = {i};")
            out.append("}")
            out.append("")
        out.append("service ToolService {")
        for t in tools:
            out.append(f"  rpc {pascal(t.name)}({pascal(t.name)}Request) returns (ToolResult);")
        out.append("}")
        return "\n".join(out)


def _enum_const(v) -> str:
    return str(v).upper().replace("-", "_").replace(" ", "_")


@register
class GraphQLSDL(SchemaRenderer):
    meta = FormatMeta(
        id="graphql_sdl",
        name="GraphQL schema (SDL)",
        family="idl",
        description=(
            "Each tool as a Mutation field with typed arguments, `!` for "
            "required, enums as real GraphQL enums, and triple-quoted "
            "descriptions."
        ),
        default_protocol="graphql_call",
        real_world_origin="GraphQL SDL",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        spec = lang("graphql")
        out: list[str] = []
        for t in tools:
            for p in t.params:
                if p.type.kind == TypeKind.ENUM:
                    out.append(f"enum {pascal(t.name)}{pascal(p.name)} {{")
                    for v in p.type.enum_values:
                        out.append(f"  {_enum_const(v)}")
                    out.append("}")
                    out.append("")
                if p.type.kind == TypeKind.OBJECT and p.type.fields:
                    out.append(f"input {pascal(t.name)}{pascal(p.name)}Input {{")
                    for f in p.type.fields:
                        bang = "!" if f.required else ""
                        out.append(f"  {camel(f.name)}: {spec.render(f.type)}{bang}")
                    out.append("}")
                    out.append("")
        out.append("type Mutation {")
        for t in tools:
            if opts.descriptions and t.description:
                out.append(f'  """{t.description}"""')
            args = []
            for p in t.params:
                if p.type.kind == TypeKind.ENUM:
                    ty = pascal(t.name) + pascal(p.name)
                elif p.type.kind == TypeKind.OBJECT and p.type.fields:
                    ty = pascal(t.name) + pascal(p.name) + "Input"
                else:
                    ty = spec.render(p.type)
                bang = "!" if p.required else ""
                args.append(f"{camel(p.name)}: {ty}{bang}")
            arglist = ", ".join(args)
            out.append(f"  {camel(t.name)}({arglist}): ToolResult")
        out.append("}")
        return "\n".join(out)


@register
class ThriftIDL(SchemaRenderer):
    meta = FormatMeta(
        id="thrift_idl",
        name="Apache Thrift IDL",
        family="idl",
        description=(
            "Thrift service methods with numbered, explicitly required/optional "
            "arguments — the most explicit optionality marking of any format."
        ),
        default_protocol="json_object",
        real_world_origin="Apache Thrift",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        spec = lang("thrift")
        out: list[str] = ["namespace py tools", "", "service ToolService {"]
        for t in tools:
            if opts.descriptions and t.description:
                out.append(f"  /** {t.description} */")
            args = []
            for i, p in enumerate(t.params, start=1):
                req = "required" if p.required else "optional"
                args.append(f"{i}: {req} {spec.render(p.type)} {p.name}")
            out.append(f"  string {t.name}(" + ", ".join(args) + "),")
            out.append("")
        out.append("}")
        return "\n".join(out)


@register
class AvroSchema(SchemaRenderer):
    meta = FormatMeta(
        id="avro_schema",
        name="Apache Avro record schemas",
        family="idl",
        description=(
            "One Avro record per tool, JSON-encoded, with union types for "
            "nullable fields. JSON syntax but a very different vocabulary from "
            "JSON Schema."
        ),
        default_protocol="json_object",
        real_world_origin="Apache Avro",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        records = []
        for t in tools:
            fields = []
            for p in t.params:
                ty = _avro_type(p.type)
                if not p.required:
                    ty = ["null", ty] if not isinstance(ty, list) else ["null", *ty]
                f = {"name": p.name, "type": ty}
                if opts.descriptions and p.description:
                    f["doc"] = p.description
                if opts.defaults and p.default is not None:
                    f["default"] = p.default
                elif not p.required:
                    f["default"] = None
                fields.append(f)
            rec = {"type": "record", "name": pascal(t.name) + "Request", "fields": fields}
            if opts.descriptions and t.description:
                rec["doc"] = t.description
            records.append(rec)
        if opts.minify:
            return json.dumps(records, separators=(",", ":"))
        return json.dumps(records, indent=opts.indent)


def _avro_type(t: TypeIR):
    if t.kind == TypeKind.ARRAY:
        return {"type": "array", "items": _avro_type(t.item) if t.item else "string"}
    if t.kind == TypeKind.OBJECT:
        return {
            "type": "record",
            "name": "Nested",
            "fields": [{"name": f.name, "type": _avro_type(f.type)} for f in t.fields],
        }
    if t.kind == TypeKind.ENUM:
        return {"type": "enum", "name": "E", "symbols": [_enum_const(v) for v in t.enum_values]}
    if t.kind == TypeKind.UNION:
        return [_avro_type(u) for u in t.union_of]
    return {
        TypeKind.STRING: "string",
        TypeKind.INTEGER: "long",
        TypeKind.NUMBER: "double",
        TypeKind.BOOLEAN: "boolean",
        TypeKind.NULL: "null",
    }.get(t.kind, "string")


@register
class WITInterface(SchemaRenderer):
    meta = FormatMeta(
        id="wit_idl",
        name="WebAssembly Component Model WIT",
        family="idl",
        description=(
            "WIT interface declarations with option<T>, list<T>, record and "
            "variant. A modern, terse IDL that models have seen very little of "
            "— a natural test of format familiarity."
        ),
        default_protocol="json_object",
        real_world_origin="WebAssembly Component Model (WIT)",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        spec = lang("wit")
        out: list[str] = ["interface tools {"]
        for t in tools:
            for p in t.params:
                if p.type.kind == TypeKind.OBJECT and p.type.fields:
                    out.append(f"  record {_kebab(t.name)}-{_kebab(p.name)} {{")
                    for f in p.type.fields:
                        ty = spec.render(f.type)
                        out.append(f"    {_kebab(f.name)}: {ty if f.required else f'option<{ty}>'},")
                    out.append("  }")
                if p.type.kind == TypeKind.ENUM:
                    out.append(f"  enum {_kebab(t.name)}-{_kebab(p.name)} {{")
                    out.append("    " + ", ".join(_kebab(str(v)) for v in p.type.enum_values))
                    out.append("  }")
            if opts.descriptions and t.description:
                out.append(f"  /// {t.description}")
            args = []
            for p in t.params:
                if p.type.kind in (TypeKind.OBJECT, TypeKind.ENUM):
                    ty = f"{_kebab(t.name)}-{_kebab(p.name)}"
                else:
                    ty = spec.render(p.type)
                args.append(f"{_kebab(p.name)}: {ty if p.required else f'option<{ty}>'}")
            out.append(f"  {_kebab(t.name)}: func({', '.join(args)}) -> result<string, string>;")
            out.append("")
        out.append("}")
        return "\n".join(out)


def _kebab(s: str) -> str:
    return s.replace("_", "-").replace(" ", "-").lower()


@register
class SmithyIDL(SchemaRenderer):
    meta = FormatMeta(
        id="smithy_idl",
        name="Smithy IDL",
        family="idl",
        description=(
            "AWS Smithy operations with `@required`, `@documentation` and "
            "structure shapes. Trait-annotated rather than syntax-annotated."
        ),
        default_protocol="json_object",
        real_world_origin="AWS Smithy",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = ['$version: "2"', "", "namespace tools", ""]
        for t in tools:
            if opts.descriptions and t.description:
                out.append(f'@documentation("{_esc(t.description)}")')
            out.append(f"operation {pascal(t.name)} {{")
            out.append(f"    input: {pascal(t.name)}Input")
            out.append("    output: ToolResult")
            out.append("}")
            out.append("")
            out.append(f"structure {pascal(t.name)}Input {{")
            for p in t.params:
                if opts.descriptions and p.description:
                    out.append(f'    @documentation("{_esc(p.description)}")')
                if p.required:
                    out.append("    @required")
                out.append(f"    {p.name}: {_smithy_type(p.type)}")
            out.append("}")
            out.append("")
        return "\n".join(out).rstrip()


def _esc(s: str) -> str:
    return s.replace('"', '\\"')


def _smithy_type(t: TypeIR) -> str:
    return {
        TypeKind.STRING: "String",
        TypeKind.INTEGER: "Integer",
        TypeKind.NUMBER: "Double",
        TypeKind.BOOLEAN: "Boolean",
        TypeKind.ARRAY: "StringList",
        TypeKind.OBJECT: "Document",
        TypeKind.ENUM: "String",
        TypeKind.UNION: "Document",
    }.get(t.kind, "String")


@register
class CapnProtoIDL(SchemaRenderer):
    meta = FormatMeta(
        id="capnproto_idl",
        name="Cap'n Proto schema",
        family="idl",
        description=("Cap'n Proto interfaces with numbered fields and inline parameter lists on each method."),
        default_protocol="json_object",
        real_world_origin="Cap'n Proto",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = ["@0xdeadbeefcafe1234;", "", "interface Tools {"]
        for i, t in enumerate(tools):
            if opts.descriptions and t.description:
                out.append(f"  # {t.description}")
            args = ", ".join(f"{camel(p.name)} :{_capnp_type(p.type)}" for p in t.params)
            out.append(f"  {camel(t.name)} @{i} ({args}) -> (result :Text);")
        out.append("}")
        return "\n".join(out)


def _capnp_type(t: TypeIR) -> str:
    if t.kind == TypeKind.ARRAY:
        return f"List({_capnp_type(t.item)})" if t.item else "List(Text)"
    return {
        TypeKind.STRING: "Text",
        TypeKind.INTEGER: "Int64",
        TypeKind.NUMBER: "Float64",
        TypeKind.BOOLEAN: "Bool",
        TypeKind.OBJECT: "AnyPointer",
        TypeKind.ENUM: "Text",
        TypeKind.UNION: "AnyPointer",
    }.get(t.kind, "Text")


@register
class FlatBuffersIDL(SchemaRenderer):
    meta = FormatMeta(
        id="flatbuffers_idl",
        name="FlatBuffers schema",
        family="idl",
        description="FlatBuffers tables and enums, one table per tool request.",
        default_protocol="json_object",
        real_world_origin="FlatBuffers",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = ["namespace tools;", ""]
        for t in tools:
            for p in t.params:
                if p.type.kind == TypeKind.ENUM:
                    out.append(
                        f"enum {pascal(t.name)}{pascal(p.name)} : byte {{ "
                        + ", ".join(_enum_const(v) for v in p.type.enum_values)
                        + " }"
                    )
            if opts.descriptions and t.description:
                out.append(f"/// {t.description}")
            out.append(f"table {pascal(t.name)}Request {{")
            for p in t.params:
                ty = _fb_type(p.type, t, p)
                d = ""
                if (
                    opts.defaults
                    and p.default is not None
                    and p.type.kind in (TypeKind.INTEGER, TypeKind.NUMBER, TypeKind.BOOLEAN)
                ):
                    d = f" = {json.dumps(p.default)}"
                req = " (required)" if p.required else ""
                out.append(f"  {p.name}:{ty}{d}{req};")
            out.append("}")
            out.append("")
        return "\n".join(out).rstrip()


def _fb_type(t: TypeIR, tool: ToolIR, p: ParamIR) -> str:
    if t.kind == TypeKind.ENUM:
        return pascal(tool.name) + pascal(p.name)
    if t.kind == TypeKind.ARRAY:
        return f"[{_fb_scalar(t.item)}]" if t.item else "[string]"
    return _fb_scalar(t)


def _fb_scalar(t: TypeIR | None) -> str:
    if t is None:
        return "string"
    return {
        TypeKind.STRING: "string",
        TypeKind.INTEGER: "long",
        TypeKind.NUMBER: "double",
        TypeKind.BOOLEAN: "bool",
        TypeKind.OBJECT: "string",
    }.get(t.kind, "string")
