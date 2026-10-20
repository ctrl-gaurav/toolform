"""JSON and JSON-Schema dialects.

This is the family every vendor documents, so it is the reference arm of the
study. The dialects differ only in surface syntax; all of them are produced
from the same ``tool_to_json_schema`` call, so any accuracy difference between
them is presentation, not content.
"""

from __future__ import annotations

import json
from typing import Any

from ..ir import ParamIR, ToolIR, TypeIR, TypeKind
from .base import FormatMeta, RenderOptions, SchemaRenderer, register
from .common import tool_to_json_schema


def _dump(obj: Any, opts: RenderOptions) -> str:
    if opts.minify:
        return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    return json.dumps(obj, indent=opts.indent, ensure_ascii=False)


# --------------------------------------------------------------------------- #


@register
class OpenAIJSONSchema(SchemaRenderer):
    meta = FormatMeta(
        id="json_schema_openai",
        name="JSON Schema (OpenAI function shape)",
        family="json",
        description=(
            "OpenAI-style function definitions: a list of "
            '{"type":"function","function":{...}} objects with a JSON Schema '
            "parameters block. The industry default."
        ),
        default_protocol="json_object",
        real_world_origin="OpenAI Chat Completions / Responses function calling",
        tags=("reference", "vendor-default"),
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        payload = [
            tool_to_json_schema(t, style="openai", descriptions=opts.descriptions, include_returns=opts.returns)
            for t in tools
        ]
        return _dump(payload, opts)


@register
class OpenAIFlatJSONSchema(SchemaRenderer):
    meta = FormatMeta(
        id="json_schema_flat",
        name="JSON Schema (flat function objects)",
        family="json",
        description=(
            "The same JSON Schema without the outer type/function wrapper: "
            '{"name":..,"description":..,"parameters":{..}}. Isolates the cost '
            "of the wrapper itself."
        ),
        default_protocol="json_object",
        real_world_origin="OpenAI legacy `functions` parameter",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        payload = [
            tool_to_json_schema(t, style="openai_flat", descriptions=opts.descriptions, include_returns=opts.returns)
            for t in tools
        ]
        return _dump(payload, opts)


@register
class AnthropicJSONSchema(SchemaRenderer):
    meta = FormatMeta(
        id="json_schema_anthropic",
        name="JSON Schema (Anthropic input_schema shape)",
        family="json",
        description=(
            "Anthropic-style tool definitions using `input_schema` instead of "
            "`parameters`. Same content, different key."
        ),
        default_protocol="json_object",
        real_world_origin="Anthropic Messages API tools",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        payload = [
            tool_to_json_schema(t, style="anthropic", descriptions=opts.descriptions, include_returns=opts.returns)
            for t in tools
        ]
        return _dump(payload, opts)


@register
class JSONSchemaDraft(SchemaRenderer):
    meta = FormatMeta(
        id="json_schema_draft2020",
        name="JSON Schema 2020-12 (full, with $schema and $defs)",
        family="json",
        description=(
            "Formal JSON Schema 2020-12 documents, one per tool, with $schema, "
            "$id and $defs for repeated sub-objects. The most verbose, most "
            "standards-correct end of the JSON axis."
        ),
        default_protocol="json_object",
        real_world_origin="JSON Schema 2020-12 specification",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        docs = []
        for t in tools:
            body = tool_to_json_schema(
                t, style="openai_flat", descriptions=opts.descriptions, include_returns=opts.returns
            )
            schema = body.pop("parameters")
            schema = {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$id": f"https://example.com/tools/{t.name}.json",
                "title": t.name,
                **({"description": t.description} if opts.descriptions and t.description else {}),
                **schema,
                "additionalProperties": False,
            }
            docs.append(schema)
        return _dump(docs, opts)


@register
class JSONCompact(SchemaRenderer):
    meta = FormatMeta(
        id="json_compact",
        name="JSON Schema (minified, no whitespace)",
        family="json",
        description=(
            "Byte-identical content to json_schema_openai with all optional "
            "whitespace removed. Pure token-cost lever with content held fixed."
        ),
        default_protocol="json_object",
        real_world_origin="Common production optimisation",
        compressed=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        payload = [
            tool_to_json_schema(t, style="openai", descriptions=opts.descriptions, include_returns=opts.returns)
            for t in tools
        ]
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


@register
class JSONMinimal(SchemaRenderer):
    meta = FormatMeta(
        id="json_minimal",
        name="JSON (names and types only)",
        family="json",
        description=(
            "Names, parameter names, types and required flags. No descriptions, "
            "no constraints, no returns. Tests how much of a schema's value is "
            "the prose rather than the structure."
        ),
        default_protocol="json_object",
        real_world_origin="Context-budget stripped schemas seen in MCP proxies",
        supports_constraints=False,
        lossy=True,
        compressed=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        payload = []
        for t in tools:
            props = {}
            req = []
            for p in t.params:
                props[p.name] = _bare_type(p.type)
                if p.required:
                    req.append(p.name)
            payload.append({"name": t.name, "params": props, "required": req})
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


@register
class NamesOnly(SchemaRenderer):
    """The true names-only arm.

    `json_minimal` is not a bare list
    of names: it carries parameter names, types, enums, nesting and
    required flags. This renderer is the bare list: one tool name per line
    and nothing else. A model can only call what it can name and must guess
    every argument, so it anchors the bottom of the schema-component ladder.
    """

    meta = FormatMeta(
        id="names_only",
        name="Tool names only",
        family="json",
        description="A bare list of the tool names, one per line: no parameters, "
        "no types, no descriptions. The floor of the schema-component ladder.",
        default_protocol="json_object",
        real_world_origin="A tool menu with no documentation",
        supports_nesting=False,
        supports_enum=False,
        supports_constraints=False,
        supports_optional=False,
        supports_returns=False,
        lossy=True,
        compressed=True,
        novel=True,
        tags=("ablation", "ladder"),
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        return "\n".join(f"- {t.name}" for t in tools)


@register
class NamesThenSchema(NamesOnly):
    """Progressive disclosure: stage one shows the
    bare list of names and asks for the one tool to use; stage two shows that
    tool's full JSON Schema alone and asks for the call. The renderer is the
    stage-one list; the runner (``two_stage`` in the tags) does the second
    stage with ``json_schema_openai`` on a universe reduced to the chosen tool.
    A deployment policy rather than a rendering: selection from names, then
    the contract of the selected tool.
    """

    meta = FormatMeta(
        id="names_then_schema",
        name="Names, then the chosen tool's schema",
        family="json",
        description="Two calls: pick a tool from a bare list of names, then write the "
        "call from that one tool's full JSON Schema. The progressive-disclosure policy.",
        default_protocol="json_object",
        real_world_origin="A tool menu with lazy documentation loading",
        supports_nesting=True,
        supports_enum=True,
        supports_constraints=True,
        supports_optional=True,
        supports_returns=True,
        lossy=False,
        compressed=True,
        novel=True,
        tags=("ablation", "ladder", "two_stage"),
    )


@register
class NamesThenSchemaV2(NamesOnly):
    """Progressive disclosure, second version.
    Same two stages as ``names_then_schema`` with three repairs: a reply that
    names no tool is a recorded selection failure and the call stage shows no
    tool (no first-tool fallback); the call is graded against the original
    catalogue, so a twin of the gold tool earns the same credit as in the
    one-shot arms; and the selection call's tokens are kept in the record.
    """

    meta = FormatMeta(
        id="names_then_schema_v2",
        name="Names, then the chosen tool's schema (v2)",
        family="json",
        description="Two calls: pick a tool from a bare list of names, then write the "
        "call from that one tool's full JSON Schema. No fallback when no tool is named; "
        "graded on the original catalogue; both calls' tokens recorded.",
        default_protocol="json_object",
        real_world_origin="A tool menu with lazy documentation loading",
        supports_nesting=True,
        supports_enum=True,
        supports_constraints=True,
        supports_optional=True,
        supports_returns=True,
        lossy=False,
        compressed=True,
        novel=True,
        tags=("ablation", "ladder", "two_stage", "two_stage_v2"),
    )


@register
class NamesDescThenSchema(NamesThenSchemaV2):
    """Disclosure v2 whose selection list carries each tool's first sentence
    of description beside its name: the menu a real deployment would show."""

    meta = FormatMeta(
        id="names_desc_then_schema",
        name="Names and one-line descriptions, then the chosen tool's schema",
        family="json",
        description="Two calls: pick a tool from a list of names with one-line "
        "descriptions, then write the call from that tool's full JSON Schema.",
        default_protocol="json_object",
        real_world_origin="A documented tool menu with lazy schema loading",
        supports_nesting=True,
        supports_enum=True,
        supports_constraints=True,
        supports_optional=True,
        supports_returns=True,
        lossy=False,
        compressed=True,
        novel=True,
        tags=("ablation", "ladder", "two_stage", "two_stage_v2", "desc_stage"),
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        lines = []
        for t in tools:
            d = (t.description or "").strip().split(". ")[0].strip().rstrip(".")
            lines.append(f"- {t.name}: {d}" if d else f"- {t.name}")
        return "\n".join(lines)


@register
class OracleThenSchema(NamesThenSchemaV2):
    """Disclosure v2 with a perfect selector: no selection call, the gold tool's
    full JSON Schema is shown alone. The ceiling of the two-stage policy; what
    is left below 100% is argument writing from one schema."""

    meta = FormatMeta(
        id="oracle_then_schema",
        name="Oracle selection, then the gold tool's schema",
        family="json",
        description="One call: the gold tool's full JSON Schema shown alone, as if a "
        "perfect selector had picked it. The ceiling of progressive disclosure.",
        default_protocol="json_object",
        real_world_origin="An upper bound, not a deployment",
        supports_nesting=True,
        supports_enum=True,
        supports_constraints=True,
        supports_optional=True,
        supports_returns=True,
        lossy=False,
        compressed=True,
        novel=True,
        tags=("ablation", "ladder", "two_stage", "two_stage_v2", "oracle"),
    )


@register
class JSONNamesAndParams(SchemaRenderer):
    """Names plus parameter names: the second rung of the
    schema-component ladder, between the bare list and `json_minimal`
    (which adds types, enums, nesting and required flags)."""

    meta = FormatMeta(
        id="json_names_params",
        name="JSON (tool and parameter names only)",
        family="json",
        description='{"name": ..., "params": [param names]} per tool: which arguments '
        "exist, but not their types, structure, requiredness or meaning.",
        default_protocol="json_object",
        real_world_origin="A signature with no types",
        supports_nesting=False,
        supports_enum=False,
        supports_constraints=False,
        supports_optional=False,
        supports_returns=False,
        lossy=True,
        compressed=True,
        novel=True,
        tags=("ablation", "ladder"),
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        payload = [{"name": t.name, "params": [p.name for p in t.params]} for t in tools]
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _bare_type(t: TypeIR) -> Any:
    if t.kind == TypeKind.ARRAY:
        return [_bare_type(t.item)] if t.item is not None else ["any"]
    if t.kind == TypeKind.OBJECT:
        return {f.name: _bare_type(f.type) for f in t.fields}
    if t.kind == TypeKind.ENUM:
        return list(t.enum_values)
    if t.kind == TypeKind.UNION:
        return "|".join(_flat_kind(u) for u in t.union_of)
    return t.kind.value


def _flat_kind(t: TypeIR) -> str:
    if t.kind == TypeKind.ARRAY:
        return "array"
    if t.kind == TypeKind.ENUM:
        return "enum"
    return t.kind.value


@register
class JSONLines(SchemaRenderer):
    meta = FormatMeta(
        id="jsonl",
        name="JSON Lines (one tool per line)",
        family="json",
        description=(
            "One complete JSON tool object per line, no enclosing array. "
            "Line-oriented layout that many models see during pretraining."
        ),
        default_protocol="json_object",
        real_world_origin="JSON Lines / NDJSON convention",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        lines = [
            json.dumps(
                tool_to_json_schema(
                    t,
                    style="openai_flat",
                    descriptions=opts.descriptions,
                    include_returns=opts.returns,
                ),
                separators=(",", ":"),
                ensure_ascii=False,
            )
            for t in tools
        ]
        return "\n".join(lines)


@register
class JSON5(SchemaRenderer):
    meta = FormatMeta(
        id="json5",
        name="JSON5 (unquoted keys, comments, trailing commas)",
        family="json",
        description=(
            "JSON5 relaxes JSON: bare keys, single quotes, and // comments "
            "carrying the descriptions. Cheaper in tokens than strict JSON."
        ),
        default_protocol="json_object",
        real_world_origin="JSON5 specification",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = ["["]
        for t in tools:
            out.append(f"{' ' * opts.indent}{{")
            pad = " " * (opts.indent * 2)
            if opts.descriptions and t.description:
                out.append(f"{pad}// {t.description}")
            out.append(f"{pad}name: '{t.name}',")
            out.append(f"{pad}params: {{")
            for p in t.params:
                ppad = " " * (opts.indent * 3)
                if opts.descriptions and p.description:
                    out.append(f"{ppad}// {p.description}")
                flag = "" if p.required else "  /* optional */"
                out.append(f"{ppad}{_json5_key(p.name)}: '{_type_sig(p.type)}',{flag}")
            out.append(f"{pad}}},")
            out.append(f"{' ' * opts.indent}}},")
        out.append("]")
        return "\n".join(out)


def _json5_key(name: str) -> str:
    return name if name.isidentifier() else f"'{name}'"


def _type_sig(t: TypeIR) -> str:
    """One-token-ish type signature reused by several compact formats."""
    if t.kind == TypeKind.ARRAY:
        return f"{_type_sig(t.item)}[]" if t.item is not None else "any[]"
    if t.kind == TypeKind.OBJECT:
        inner = ", ".join(f"{f.name}: {_type_sig(f.type)}" for f in t.fields)
        return "{" + inner + "}"
    if t.kind == TypeKind.ENUM:
        return "|".join(json.dumps(v) for v in t.enum_values)
    if t.kind == TypeKind.UNION:
        return "|".join(_type_sig(u) for u in t.union_of)
    return t.kind.value


@register
class HJSON(SchemaRenderer):
    meta = FormatMeta(
        id="hjson",
        name="Hjson (quote-free human JSON)",
        family="json",
        description=(
            "Hjson drops quotes and commas entirely. Reads like an indented "
            "key/value block while remaining a JSON superset."
        ),
        default_protocol="json_object",
        real_world_origin="Hjson specification",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            out.append("{")
            out.append(f"  name: {t.name}")
            if opts.descriptions and t.description:
                out.append(f"  description: {t.description}")
            out.append("  params: {")
            for p in t.params:
                req = "required" if p.required else "optional"
                line = f"    {p.name}: {_type_sig(p.type)} ({req})"
                if opts.descriptions and p.description:
                    line += f" - {p.description}"
                out.append(line)
            out.append("  }")
            out.append("}")
        return "\n".join(out)


@register
class JSONC(SchemaRenderer):
    meta = FormatMeta(
        id="jsonc",
        name="JSON with comments (JSONC)",
        family="json",
        description=(
            "Strict JSON structure with every description moved out of the "
            "data and into a // comment above its key. Separates prose from "
            "structure without removing either."
        ),
        default_protocol="json_object",
        real_world_origin="VS Code / tsconfig JSONC",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        pad = " " * opts.indent
        out: list[str] = ["["]
        for t in tools:
            if opts.descriptions and t.description:
                out.append(f"{pad}// {t.description}")
            out.append(f"{pad}{{")
            out.append(f'{pad * 2}"name": "{t.name}",')
            out.append(f'{pad * 2}"parameters": {{')
            for p in t.params:
                if opts.descriptions and p.description:
                    out.append(f"{pad * 3}// {p.description}")
                if not p.required:
                    out.append(
                        f"{pad * 3}// optional"
                        + (f", default {json.dumps(p.default)}" if p.default is not None and opts.defaults else "")
                    )
                out.append(f'{pad * 3}"{p.name}": "{_type_sig(p.type)}",')
            out.append(f"{pad * 2}}}")
            out.append(f"{pad}}},")
        out.append("]")
        return "\n".join(out)


@register
class DottedNDJSON(SchemaRenderer):
    meta = FormatMeta(
        id="json_dotted_paths",
        name="Flattened dotted-path JSON (novel)",
        family="json",
        description=(
            "Every leaf of every schema written as one flat dotted path with "
            "its type: `book_flight.passenger.name: string!`. Nesting is "
            "encoded in the key, so structure survives with no braces at all."
        ),
        default_protocol="json_object",
        novel=True,
        tags=("compression", "flat"),
        compressed=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        lines: list[str] = []
        for t in tools:
            if opts.descriptions and t.description:
                lines.append(f"# {t.name}: {t.description}")
            for p in t.params:
                lines.extend(_dotted(t.name, p, opts))
        return "\n".join(lines)


def _dotted(prefix: str, p: ParamIR, opts: RenderOptions) -> list[str]:
    path = f"{prefix}.{p.name}"
    t = p.type
    mark = "!" if p.required else "?"
    if t.kind == TypeKind.OBJECT and t.fields:
        out = []
        for f in t.fields:
            out.extend(_dotted(path, f, opts))
        return out
    if t.kind == TypeKind.ARRAY and t.item is not None and t.item.kind == TypeKind.OBJECT:
        out = []
        for f in t.item.fields:
            out.extend(_dotted(path + "[]", f, opts))
        return out
    desc = f"  # {p.description}" if opts.descriptions and p.description else ""
    return [f"{path}: {_type_sig(t)}{mark}{desc}"]
