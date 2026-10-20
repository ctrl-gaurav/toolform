"""Configuration languages.

Config languages are an interesting middle ground: they are structured like
JSON but read like prose, and models have seen a lot of them in repositories.
Several of them (HCL, CUE, Dhall, Nix, KDL) are rare enough in pretraining
that they double as a familiarity probe.
"""

from __future__ import annotations

import json

from ..ir import ToolIR, TypeIR, TypeKind
from .base import FormatMeta, RenderOptions, SchemaRenderer, register


def _simple_type(t: TypeIR) -> str:
    if t.kind == TypeKind.ARRAY:
        return f"list of {_simple_type(t.item)}" if t.item else "list"
    if t.kind == TypeKind.ENUM:
        return "enum"
    if t.kind == TypeKind.UNION:
        return "|".join(_simple_type(u) for u in t.union_of)
    return t.kind.value


@register
class TOMLTools(SchemaRenderer):
    meta = FormatMeta(
        id="toml",
        name="TOML tool tables",
        family="config",
        description=(
            "`[[tool]]` array-of-tables with `[tool.params.name]` subtables. "
            "Section headers make the tool boundary very explicit."
        ),
        default_protocol="toml_call",
        real_world_origin="TOML / pyproject-style configuration",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            out.append("[[tool]]")
            out.append(f'name = "{t.name}"')
            if opts.descriptions and t.description:
                out.append(f"description = {json.dumps(t.description)}")
            for p in t.params:
                out.append("")
                out.append(f"[tool.params.{p.name}]")
                out.append(f'type = "{_simple_type(p.type)}"')
                out.append(f"required = {str(p.required).lower()}")
                if p.type.kind == TypeKind.ENUM:
                    out.append("values = " + json.dumps(list(p.type.enum_values)))
                if opts.descriptions and p.description:
                    out.append(f"description = {json.dumps(p.description)}")
                if opts.defaults and p.default is not None:
                    out.append(f"default = {json.dumps(p.default)}")
            out.append("")
        return "\n".join(out).rstrip()


@register
class INITools(SchemaRenderer):
    meta = FormatMeta(
        id="ini",
        name="INI sections",
        family="config",
        description=(
            "`[tool_name]` sections with `param = type (required)` lines. About as flat as a structured format can get."
        ),
        default_protocol="key_value_call",
        real_world_origin="INI / ConfigParser",
        lossy=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            out.append(f"[{t.name}]")
            if opts.descriptions and t.description:
                out.append(f"; {t.description}")
            for p in t.params:
                req = "required" if p.required else "optional"
                line = f"{p.name} = {_simple_type(p.type)} ({req})"
                if p.type.kind == TypeKind.ENUM:
                    line += " one of: " + "|".join(str(v) for v in p.type.enum_values)
                out.append(line)
                if opts.descriptions and p.description:
                    out.append(f"; {p.description}")
            out.append("")
        return "\n".join(out).rstrip()


@register
class HCLTools(SchemaRenderer):
    meta = FormatMeta(
        id="hcl",
        name="HCL (Terraform-style) blocks",
        family="config",
        description=(
            '`tool "name" { variable "x" { type = string ... } }`. HCL blocks look like code but behave like config.'
        ),
        default_protocol="json_object",
        real_world_origin="HashiCorp Configuration Language",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            out.append(f'tool "{t.name}" {{')
            if opts.descriptions and t.description:
                out.append(f"  description = {json.dumps(t.description)}")
            for p in t.params:
                out.append(f'  variable "{p.name}" {{')
                out.append(f"    type      = {_hcl_type(p.type)}")
                out.append(f"    required  = {str(p.required).lower()}")
                if opts.descriptions and p.description:
                    out.append(f"    description = {json.dumps(p.description)}")
                if p.type.kind == TypeKind.ENUM:
                    out.append("    allowed   = " + json.dumps(list(p.type.enum_values)))
                if opts.defaults and p.default is not None:
                    out.append(f"    default   = {json.dumps(p.default)}")
                out.append("  }")
            out.append("}")
            out.append("")
        return "\n".join(out).rstrip()


def _hcl_type(t: TypeIR) -> str:
    if t.kind == TypeKind.ARRAY:
        return f"list({_hcl_type(t.item)})" if t.item else "list(string)"
    if t.kind == TypeKind.OBJECT:
        return "object({" + ", ".join(f"{f.name} = {_hcl_type(f.type)}" for f in t.fields) + "})"
    return {
        TypeKind.STRING: "string",
        TypeKind.INTEGER: "number",
        TypeKind.NUMBER: "number",
        TypeKind.BOOLEAN: "bool",
        TypeKind.ENUM: "string",
    }.get(t.kind, "any")


@register
class CUETools(SchemaRenderer):
    meta = FormatMeta(
        id="cue",
        name="CUE definitions",
        family="config",
        description=(
            "CUE `#Tool` definitions where constraints are part of the type "
            "lattice (`int & >=0 & <=100`). Constraints and types are the same "
            "thing here, unlike everywhere else in the study."
        ),
        default_protocol="json_object",
        real_world_origin="CUE language",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            if opts.descriptions and t.description:
                out.append(f"// {t.description}")
            out.append(f"#{_pascal(t.name)}: {{")
            for p in t.params:
                q = "" if p.required else "?"
                ty = _cue_type(p.type, opts)
                cmt = f"  // {p.description}" if opts.descriptions and p.description else ""
                out.append(f"  {p.name}{q}: {ty}{cmt}")
            out.append("}")
            out.append("")
        return "\n".join(out).rstrip()


def _pascal(s: str) -> str:
    return "".join(w[:1].upper() + w[1:] for w in s.split("_") if w)


def _cue_type(t: TypeIR, opts: RenderOptions) -> str:
    if t.kind == TypeKind.ENUM:
        return " | ".join(json.dumps(v) for v in t.enum_values)
    if t.kind == TypeKind.ARRAY:
        return f"[...{_cue_type(t.item, opts)}]" if t.item else "[...string]"
    if t.kind == TypeKind.OBJECT:
        return (
            "{" + ", ".join(f"{f.name}{'' if f.required else '?'}: {_cue_type(f.type, opts)}" for f in t.fields) + "}"
        )
    if t.kind == TypeKind.UNION:
        return " | ".join(_cue_type(u, opts) for u in t.union_of)
    base = {
        TypeKind.STRING: "string",
        TypeKind.INTEGER: "int",
        TypeKind.NUMBER: "number",
        TypeKind.BOOLEAN: "bool",
    }.get(t.kind, "_")
    if opts.constraints:
        c = t.constraints
        parts = [base]
        if c.minimum is not None:
            parts.append(f">={c.minimum}")
        if c.maximum is not None:
            parts.append(f"<={c.maximum}")
        if c.pattern:
            parts.append(f"=~{json.dumps(c.pattern)}")
        return " & ".join(parts)
    return base


@register
class DhallTools(SchemaRenderer):
    meta = FormatMeta(
        id="dhall",
        name="Dhall record types",
        family="config",
        description=(
            "Dhall record types with `Optional` fields. A total, typed config "
            "language that almost never appears in pretraining corpora."
        ),
        default_protocol="json_object",
        real_world_origin="Dhall configuration language",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            if opts.descriptions and t.description:
                out.append(f"-- {t.description}")
            out.append(f"let {t.name} : Type = {{")
            for i, p in enumerate(t.params):
                ty = _dhall_type(p.type)
                if not p.required:
                    ty = f"Optional {ty}"
                lead = "  " if i == 0 else ", "
                out.append(f"  {lead}{p.name} : {ty}")
                if opts.descriptions and p.description:
                    out.append(f"    -- {p.description}")
            out.append("  }")
            out.append("")
        return "\n".join(out).rstrip()


def _dhall_type(t: TypeIR) -> str:
    if t.kind == TypeKind.ARRAY:
        return f"List {_dhall_type(t.item)}" if t.item else "List Text"
    if t.kind == TypeKind.OBJECT:
        return "{ " + ", ".join(f"{f.name} : {_dhall_type(f.type)}" for f in t.fields) + " }"
    if t.kind == TypeKind.ENUM:
        return "< " + " | ".join(str(v).replace(" ", "_") for v in t.enum_values) + " >"
    return {
        TypeKind.STRING: "Text",
        TypeKind.INTEGER: "Natural",
        TypeKind.NUMBER: "Double",
        TypeKind.BOOLEAN: "Bool",
    }.get(t.kind, "Text")


@register
class JsonnetTools(SchemaRenderer):
    meta = FormatMeta(
        id="jsonnet",
        name="Jsonnet function definitions",
        family="config",
        description=(
            "Jsonnet `local` functions with default arguments — a config "
            "language whose unit of reuse is literally a function."
        ),
        default_protocol="json_object",
        real_world_origin="Jsonnet",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            if opts.descriptions and t.description:
                out.append(f"// {t.description}")
            args = []
            for p in t.params:
                if p.required:
                    args.append(p.name)
                else:
                    args.append(f"{p.name}={json.dumps(p.default) if p.default is not None else 'null'}")
            out.append(f"local {t.name}({', '.join(args)}) = {{")
            for p in t.params:
                cmt = f"  // {p.description}" if opts.descriptions and p.description else ""
                out.append(f"  {p.name}: {p.name},{cmt}")
            out.append("};")
            out.append("")
        return "\n".join(out).rstrip()


@register
class NixTools(SchemaRenderer):
    meta = FormatMeta(
        id="nix_expr",
        name="Nix expressions (novel)",
        family="config",
        description=(
            "Tools as Nix functions with attribute-set arguments and `mkOption` "
            "style type declarations. Lazily-evaluated config as an interface."
        ),
        default_protocol="json_object",
        novel=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = ["{ lib, ... }:", "{"]
        for t in tools:
            out.append(f"  {t.name} = {{")
            if opts.descriptions and t.description:
                out.append(f"    # {t.description}")
            out.append("    options = {")
            for p in t.params:
                out.append(f"      {p.name} = lib.mkOption {{")
                out.append(f"        type = lib.types.{_nix_type(p.type)};")
                if opts.descriptions and p.description:
                    out.append(f"        description = {json.dumps(p.description)};")
                if opts.defaults and p.default is not None:
                    out.append(f"        default = {json.dumps(p.default)};")
                elif not p.required:
                    out.append("        default = null;")
                out.append("      };")
            out.append("    };")
            out.append("  };")
        out.append("}")
        return "\n".join(out)


def _nix_type(t: TypeIR) -> str:
    if t.kind == TypeKind.ARRAY:
        return f"listOf {_nix_type(t.item)}" if t.item else "listOf str"
    if t.kind == TypeKind.ENUM:
        return "enum [ " + " ".join(json.dumps(v) for v in t.enum_values) + " ]"
    if t.kind == TypeKind.OBJECT:
        return "attrs"
    return {
        TypeKind.STRING: "str",
        TypeKind.INTEGER: "int",
        TypeKind.NUMBER: "float",
        TypeKind.BOOLEAN: "bool",
    }.get(t.kind, "str")


@register
class KDLTools(SchemaRenderer):
    meta = FormatMeta(
        id="kdl",
        name="KDL document language (novel)",
        family="config",
        description=(
            'KDL nodes: `tool "name" { param "x" type=string required=#true }`. '
            "A recent, very compact document language most models have barely "
            "seen."
        ),
        default_protocol="json_object",
        novel=True,
        compressed=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            head = f'tool "{t.name}"'
            if opts.descriptions and t.description:
                head += f" description={json.dumps(t.description)}"
            out.append(head + " {")
            for p in t.params:
                bits = [f'param "{p.name}"', f'type="{_simple_type(p.type)}"']
                bits.append(f"required=#{str(p.required).lower()}")
                if p.type.kind == TypeKind.ENUM:
                    bits.append("values=" + json.dumps("|".join(str(v) for v in p.type.enum_values)))
                if opts.descriptions and p.description:
                    bits.append("doc=" + json.dumps(p.description))
                out.append("    " + " ".join(bits))
            out.append("}")
        return "\n".join(out)


@register
class EDNTools(SchemaRenderer):
    meta = FormatMeta(
        id="edn",
        name="EDN (Clojure data notation)",
        family="config",
        description=("EDN maps with keyword keys and clojure.spec-style predicates. Data-as-code in a Lisp dialect."),
        default_protocol="sexpr_call",
        real_world_origin="Clojure EDN / clojure.spec",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = ["["]
        for t in tools:
            out.append(" {:name " + f'"{t.name}"')
            if opts.descriptions and t.description:
                out.append(f'  :doc "{t.description}"')
            out.append("  :params [")
            for p in t.params:
                bits = [f':name "{p.name}"', f":type :{_simple_type(p.type)}", f":required {str(p.required).lower()}"]
                if p.type.kind == TypeKind.ENUM:
                    bits.append(":enum #{" + " ".join(json.dumps(v) for v in p.type.enum_values) + "}")
                if opts.descriptions and p.description:
                    bits.append(f':doc "{p.description}"')
                out.append("    {" + " ".join(bits) + "}")
            out.append("  ]}")
        out.append("]")
        return "\n".join(out)


@register
class SExprTools(SchemaRenderer):
    meta = FormatMeta(
        id="sexpr",
        name="S-expressions",
        family="config",
        description=(
            "`(deftool name (param type required) ...)` — parenthesised prefix "
            "notation. Minimal syntax, maximal nesting."
        ),
        default_protocol="sexpr_call",
        real_world_origin="Lisp / Scheme s-expressions",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            out.append(f"(deftool {t.name}")
            if opts.descriptions and t.description:
                out.append(f'  (doc "{t.description}")')
            for p in t.params:
                req = "required" if p.required else "optional"
                extra = ""
                if p.type.kind == TypeKind.ENUM:
                    extra = " (one-of " + " ".join(json.dumps(v) for v in p.type.enum_values) + ")"
                doc = f' "{p.description}"' if opts.descriptions and p.description else ""
                out.append(f"  (param {p.name} {_simple_type(p.type)} {req}{extra}{doc})")
            out.append(")")
        return "\n".join(out)


@register
class StarlarkTools(SchemaRenderer):
    meta = FormatMeta(
        id="starlark",
        name="Starlark rule definitions",
        family="config",
        description=(
            "Bazel-flavoured Starlark rules with `attr.string(mandatory=True)` "
            "declarations. Python-shaped syntax, config semantics."
        ),
        default_protocol="python_call",
        real_world_origin="Bazel Starlark",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            out.append(f"{t.name} = rule(")
            if opts.descriptions and t.description:
                out.append(f"    doc = {json.dumps(t.description)},")
            out.append("    attrs = {")
            for p in t.params:
                attr = {
                    TypeKind.STRING: "attr.string",
                    TypeKind.INTEGER: "attr.int",
                    TypeKind.NUMBER: "attr.int",
                    TypeKind.BOOLEAN: "attr.bool",
                    TypeKind.ARRAY: "attr.string_list",
                    TypeKind.OBJECT: "attr.string_dict",
                    TypeKind.ENUM: "attr.string",
                }.get(p.type.kind, "attr.string")
                bits = [f"mandatory = {str(p.required).title()}"]
                if p.type.kind == TypeKind.ENUM:
                    bits.append("values = " + json.dumps(list(p.type.enum_values)))
                if opts.descriptions and p.description:
                    bits.append("doc = " + json.dumps(p.description))
                if opts.defaults and p.default is not None:
                    bits.append("default = " + json.dumps(p.default))
                out.append(f'        "{p.name}": {attr}({", ".join(bits)}),')
            out.append("    },")
            out.append(")")
            out.append("")
        return "\n".join(out).rstrip()
