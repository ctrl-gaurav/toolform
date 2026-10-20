"""TypeScript-flavoured interfaces.

TypeScript gets its own module because it is the format most often proposed as
"the compact alternative to JSON Schema", and because it has three genuinely
different presentations: inline signatures, a .d.ts declaration file with
JSDoc, and a namespace-scoped variant that mirrors what some vendors put in
their system prompts.
"""

from __future__ import annotations

from ..ir import ParamIR, ToolIR, TypeIR, TypeKind
from .base import FormatMeta, RenderOptions, SchemaRenderer, register, wrap_comment
from .common import (
    collect_object_types,
    js_value,
    lang,
    object_type_name,
    ordered_params,
    pascal,
)

TS = lang("typescript")


def _ts_type(t: TypeIR, tool: ToolIR | None = None, p: ParamIR | None = None) -> str:
    if t.kind == TypeKind.OBJECT and t.fields:
        if tool is not None and p is not None:
            return object_type_name(tool, p)
        inner = "; ".join(f"{f.name}{'' if f.required else '?'}: {_ts_type(f.type)}" for f in t.fields)
        return "{ " + inner + " }"
    if t.kind == TypeKind.ARRAY and t.item is not None:
        inner = _ts_type(t.item, tool, p)
        return f"{inner}[]" if inner.isidentifier() or inner.endswith("]") else f"({inner})[]"
    if t.kind == TypeKind.ENUM:
        return " | ".join(js_value(v) for v in t.enum_values)
    if t.kind == TypeKind.UNION:
        return " | ".join(_ts_type(u, tool, p) for u in t.union_of)
    return TS.render(t)


@register
class TypeScriptSignatures(SchemaRenderer):
    meta = FormatMeta(
        id="typescript",
        name="TypeScript function signatures",
        family="code",
        description=(
            "One `declare function` per tool with an inline parameter object, "
            "JSDoc comments for the prose, and named interfaces for nested "
            "objects."
        ),
        default_protocol="json_object",
        real_world_origin="TypeScript; used by several agent frameworks",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            for name, obj in collect_object_types(t):
                out.append(f"interface {name} {{")
                for f in obj.fields:
                    q = "" if f.required else "?"
                    if opts.descriptions and f.description:
                        out.append(f"  /** {f.description} */")
                    out.append(f"  {f.name}{q}: {_ts_type(f.type)};")
                out.append("}")
                out.append("")
            if opts.descriptions and (t.description or any(p.description for p in t.params)):
                out.append("/**")
                if t.description:
                    out.append(f" * {t.description}")
                for p in t.params:
                    if p.description:
                        out.append(f" * @param {p.name} - {p.description}")
                if opts.returns and t.returns_description:
                    out.append(f" * @returns {t.returns_description}")
                out.append(" */")
            args = ", ".join(_ts_param(t, p, opts) for p in ordered_params(t))
            ret = _ts_type(t.returns) if (opts.returns and t.returns is not None) else "unknown"
            out.append(f"declare function {t.name}({args}): {ret};")
            out.append("")
        return "\n".join(out).rstrip()


def _ts_param(t: ToolIR, p: ParamIR, opts: RenderOptions) -> str:
    q = "" if p.required else "?"
    default = ""
    if opts.defaults and not p.required and p.default is not None:
        q = ""
        default = f" = {js_value(p.default)}"
    return f"{p.name}{q}: {_ts_type(p.type, t, p)}{default}"


@register
class TypeScriptDTS(SchemaRenderer):
    meta = FormatMeta(
        id="typescript_dts",
        name="TypeScript declaration file (.d.ts, namespaced)",
        family="code",
        description=(
            "A `declare namespace tools { ... }` block: exactly the shape some "
            "vendors inject into system prompts for their built-in tools."
        ),
        default_protocol="json_object",
        real_world_origin="Vendor system-prompt tool declarations",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = ["declare namespace tools {"]
        for t in tools:
            if opts.descriptions and t.description:
                out.append(wrap_comment(t.description, "  // "))
            for p in t.params:
                if opts.descriptions and p.description:
                    out.append(f"  // {p.name}: {p.description}")
            args = ", ".join(_ts_param(t, p, opts) for p in ordered_params(t))
            ret = _ts_type(t.returns) if (opts.returns and t.returns is not None) else "any"
            out.append(f"  function {t.name}({args}): {ret};")
            out.append("")
        out.append("}")
        return "\n".join(out)


@register
class TypeScriptInterfaceArg(SchemaRenderer):
    meta = FormatMeta(
        id="typescript_interface_arg",
        name="TypeScript single-argument interfaces",
        family="code",
        description=(
            "Every tool takes one typed args object declared as its own "
            "interface. Matches how JSON tool calls actually arrive, so the "
            "signature and the call shape line up exactly."
        ),
        default_protocol="json_object",
        real_world_origin="Common TypeScript agent SDK pattern",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            iface = pascal(t.name) + "Args"
            if opts.descriptions and t.description:
                out.append(f"/** {t.description} */")
            out.append(f"interface {iface} {{")
            for p in t.params:
                if opts.descriptions and p.description:
                    out.append(f"  /** {p.description} */")
                q = "" if p.required else "?"
                out.append(f"  {p.name}{q}: {_ts_type(p.type)};")
            out.append("}")
            ret = _ts_type(t.returns) if (opts.returns and t.returns is not None) else "unknown"
            out.append(f"declare function {t.name}(args: {iface}): {ret};")
            out.append("")
        return "\n".join(out).rstrip()


@register
class TypeScriptCompact(SchemaRenderer):
    meta = FormatMeta(
        id="typescript_compact",
        name="TypeScript signatures, one line each",
        family="code",
        description=(
            "Signature-only TypeScript: no comments, no interfaces, one line "
            "per tool. The cheapest presentation that still carries full types."
        ),
        default_protocol="json_object",
        real_world_origin="TypeScript",
        compressed=True,
        lossy=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        lines = []
        for t in tools:
            args = ", ".join(f"{p.name}{'' if p.required else '?'}: {_ts_type(p.type)}" for p in t.params)
            lines.append(f"{t.name}({args})")
        return "\n".join(lines)
