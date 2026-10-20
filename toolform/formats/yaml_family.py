"""YAML dialects and OpenAPI.

YAML is the most common "we save tokens" recommendation in practitioner blogs,
so it gets several variants: block, flow, minimal, anchored, and the two
OpenAPI serialisations that real API-backed agents actually consume.
"""

from __future__ import annotations

import json
from typing import Any

from ..ir import ToolIR, TypeIR, TypeKind
from .base import FormatMeta, RenderOptions, SchemaRenderer, register
from .common import kebab, tool_to_json_schema, type_to_json_schema


def _yaml_dump(obj: Any, opts: RenderOptions, *, flow: bool = False) -> str:
    try:
        import yaml  # type: ignore

        return yaml.safe_dump(
            obj,
            sort_keys=False,
            default_flow_style=flow,
            indent=opts.indent,
            width=100000 if flow else 88,
            allow_unicode=True,
        ).rstrip()
    except Exception:  # noqa: BLE001 - fall back to a hand-rolled emitter
        return _mini_yaml(obj, opts.indent, flow=flow)


def _mini_yaml(obj: Any, indent: int, level: int = 0, *, flow: bool = False) -> str:
    """Small YAML emitter so the harness works even without PyYAML."""
    pad = " " * (indent * level)
    if flow:
        return json.dumps(obj, separators=(", ", ": "))
    if isinstance(obj, dict):
        if not obj:
            return pad + "{}"
        lines = []
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}{k}:")
                lines.append(_mini_yaml(v, indent, level + 1))
            else:
                lines.append(f"{pad}{k}: {_scalar(v)}")
        return "\n".join(lines)
    if isinstance(obj, list):
        if not obj:
            return pad + "[]"
        lines = []
        for v in obj:
            if isinstance(v, (dict, list)) and v:
                body = _mini_yaml(v, indent, level + 1)
                body = body[len(pad) + indent :] if body.startswith(pad) else body
                lines.append(f"{pad}- " + body.lstrip().split("\n")[0])
                rest = body.split("\n")[1:]
                lines.extend(rest)
            else:
                lines.append(f"{pad}- {_scalar(v)}")
        return "\n".join(lines)
    return pad + _scalar(obj)


def _scalar(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        if v == "" or any(ch in v for ch in ":#{}[]&*!|>'\"%@`") or v.strip() != v:
            return json.dumps(v)
        return v
    return json.dumps(v)


# --------------------------------------------------------------------------- #


@register
class YAMLSchema(SchemaRenderer):
    meta = FormatMeta(
        id="yaml_schema",
        name="YAML schema (block style)",
        family="yaml",
        description=(
            "The same JSON Schema content emitted as block-style YAML. The "
            "most common 'save tokens' recommendation in practice."
        ),
        default_protocol="json_object",
        real_world_origin="Widely used in agent prompt engineering",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        payload = [
            tool_to_json_schema(t, style="openai_flat", descriptions=opts.descriptions, include_returns=opts.returns)
            for t in tools
        ]
        return _yaml_dump(payload, opts)


@register
class YAMLFlow(SchemaRenderer):
    meta = FormatMeta(
        id="yaml_flow",
        name="YAML schema (flow style)",
        family="yaml",
        description=(
            "YAML in flow style — inline maps and sequences on one line. "
            "Structurally identical to block YAML but visually JSON-like."
        ),
        default_protocol="json_object",
        real_world_origin="YAML 1.2 flow style",
        compressed=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        payload = [
            tool_to_json_schema(t, style="openai_flat", descriptions=opts.descriptions, include_returns=opts.returns)
            for t in tools
        ]
        return _yaml_dump(payload, opts, flow=True)


@register
class YAMLMinimal(SchemaRenderer):
    meta = FormatMeta(
        id="yaml_minimal",
        name="YAML (names and types only)",
        family="yaml",
        description=(
            "YAML counterpart of json_minimal: tool name, parameter names, types, required markers. Nothing else."
        ),
        default_protocol="json_object",
        real_world_origin="Context-budget stripped YAML schemas",
        supports_constraints=False,
        lossy=True,
        compressed=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        lines: list[str] = []
        for t in tools:
            lines.append(f"{t.name}:")
            for p in t.params:
                mark = "" if p.required else "?"
                lines.append(f"  {p.name}{mark}: {_short_type(p.type)}")
        return "\n".join(lines)


def _short_type(t: TypeIR) -> str:
    if t.kind == TypeKind.ARRAY:
        return f"[{_short_type(t.item)}]" if t.item is not None else "[any]"
    if t.kind == TypeKind.OBJECT:
        return "{" + ", ".join(f"{f.name}: {_short_type(f.type)}" for f in t.fields) + "}"
    if t.kind == TypeKind.ENUM:
        return "enum(" + "|".join(str(v) for v in t.enum_values) + ")"
    if t.kind == TypeKind.UNION:
        return "|".join(_short_type(u) for u in t.union_of)
    return t.kind.value


@register
class YAMLDocumented(SchemaRenderer):
    meta = FormatMeta(
        id="yaml_documented",
        name="YAML with comment documentation",
        family="yaml",
        description=(
            "Structure in YAML, prose in `#` comments beside each key. Splits "
            "the documentation channel from the data channel."
        ),
        default_protocol="json_object",
        real_world_origin="Kubernetes/Ansible style annotated YAML",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        lines: list[str] = []
        for t in tools:
            if opts.descriptions and t.description:
                lines.append(f"# {t.description}")
            lines.append(f"- name: {t.name}")
            lines.append("  parameters:")
            for p in t.params:
                comment = ""
                if opts.descriptions and p.description:
                    comment = f"  # {p.description}"
                req = "required" if p.required else "optional"
                lines.append(f"    {p.name}:{comment}")
                lines.append(f"      type: {_short_type(p.type)}")
                lines.append(f"      presence: {req}")
                if opts.defaults and p.default is not None:
                    lines.append(f"      default: {_scalar(p.default)}")
            lines.append("")
        return "\n".join(lines).rstrip()


@register
class YAMLAnchors(SchemaRenderer):
    meta = FormatMeta(
        id="yaml_anchors",
        name="YAML with anchors and aliases (novel)",
        family="yaml",
        description=(
            "Repeated sub-schemas are defined once under an anchor (&addr) and "
            "referenced with aliases (*addr). A large tool universe with shared "
            "structure shrinks a lot; the question is whether models can follow "
            "the indirection."
        ),
        default_protocol="json_object",
        novel=True,
        tags=("compression", "indirection"),
        compressed=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        # find object types that appear more than once across the universe
        counts: dict[str, int] = {}
        for t in tools:
            for p in t.params:
                key = _obj_key(p.type)
                if key:
                    counts[key] = counts.get(key, 0) + 1
        shared = {k: f"s{i}" for i, k in enumerate(k for k, v in counts.items() if v > 1)}

        lines: list[str] = []
        if shared:
            lines.append("definitions:")
            for key, anchor in shared.items():
                lines.append(f"  {anchor}: &{anchor} {key}")
            lines.append("")
        lines.append("tools:")
        for t in tools:
            lines.append(f"  - name: {t.name}")
            if opts.descriptions and t.description:
                lines.append(f"    description: {_scalar(t.description)}")
            lines.append("    params:")
            for p in t.params:
                key = _obj_key(p.type)
                mark = "" if p.required else "?"
                if key and key in shared:
                    lines.append(f"      {p.name}{mark}: *{shared[key]}")
                else:
                    lines.append(f"      {p.name}{mark}: {_short_type(p.type)}")
        return "\n".join(lines)


def _obj_key(t: TypeIR) -> str | None:
    if t.kind == TypeKind.OBJECT and t.fields:
        return "{" + ", ".join(f"{f.name}: {_short_type(f.type)}" for f in t.fields) + "}"
    return None


@register
class OpenAPIYAML(SchemaRenderer):
    meta = FormatMeta(
        id="openapi_yaml",
        name="OpenAPI 3.1 (YAML)",
        family="yaml",
        description=(
            "Each tool as an OpenAPI operation with operationId, summary and a "
            "requestBody schema. What an agent sees when tools come from a real "
            "REST service."
        ),
        default_protocol="json_object",
        real_world_origin="OpenAPI 3.1 specification",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        return _yaml_dump(_openapi_doc(tools, opts), opts)


@register
class OpenAPIJSON(SchemaRenderer):
    meta = FormatMeta(
        id="openapi_json",
        name="OpenAPI 3.1 (JSON)",
        family="json",
        description="The same OpenAPI document serialised as JSON.",
        default_protocol="json_object",
        real_world_origin="OpenAPI 3.1 specification",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        doc = _openapi_doc(tools, opts)
        if opts.minify:
            return json.dumps(doc, separators=(",", ":"))
        return json.dumps(doc, indent=opts.indent)


def _openapi_doc(tools: list[ToolIR], opts: RenderOptions) -> dict[str, Any]:
    paths: dict[str, Any] = {}
    for t in tools:
        props: dict[str, Any] = {}
        required: list[str] = []
        for p in t.params:
            s = type_to_json_schema(p.type)
            if opts.descriptions and p.description:
                s["description"] = p.description
            if opts.defaults and p.default is not None:
                s["default"] = p.default
            props[p.name] = s
            if p.required:
                required.append(p.name)
        body_schema: dict[str, Any] = {"type": "object", "properties": props}
        if required:
            body_schema["required"] = required
        op: dict[str, Any] = {
            "operationId": t.name,
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": body_schema}},
            },
            "responses": {"200": {"description": t.returns_description or "Success"}},
        }
        if opts.descriptions and t.description:
            op["summary"] = t.description
        paths[f"/{kebab(t.name)}"] = {"post": op}
    return {
        "openapi": "3.1.0",
        "info": {"title": "Tool API", "version": "1.0.0"},
        "paths": paths,
    }
