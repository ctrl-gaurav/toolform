"""Formal grammars over the set of legal calls.

Instead of describing what a tool *is*, these formats describe what a legal
call *looks like*. That is a real alternative: constrained-decoding stacks
already compile schemas into grammars, so showing the grammar directly is the
natural question to ask. As far as we can tell nobody has tested whether a
model reads a grammar better or worse than the schema it came from.
"""

from __future__ import annotations

import json

from ..ir import ParamIR, ToolIR, TypeIR, TypeKind
from .base import FormatMeta, RenderOptions, SchemaRenderer, register


def _term_for(t: TypeIR) -> str:
    return {
        TypeKind.STRING: "STRING",
        TypeKind.INTEGER: "INT",
        TypeKind.NUMBER: "NUMBER",
        TypeKind.BOOLEAN: "BOOL",
        TypeKind.NULL: "NULL",
    }.get(t.kind, "VALUE")


def _rule_name(tool: str, param: str) -> str:
    return f"{tool}_{param}".replace("-", "_")


@register
class EBNFGrammar(SchemaRenderer):
    meta = FormatMeta(
        id="ebnf_grammar",
        name="EBNF grammar of legal calls (novel)",
        family="grammar",
        description=(
            "An EBNF grammar whose language is exactly the set of well-formed "
            "calls. Optionality is `[...]`, enums are alternations, nesting is "
            "recursion. The schema becomes a production system."
        ),
        default_protocol="json_object",
        novel=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = ["call ::= " + " | ".join(f"{t.name}_call" for t in tools), ""]
        for t in tools:
            if opts.descriptions and t.description:
                out.append(f"(* {t.description} *)")
            req = [p for p in t.params if p.required]
            optp = [p for p in t.params if not p.required]
            body = ", ".join(f'"{p.name}" ":" {_rule_name(t.name, p.name)}' for p in req)
            for p in optp:
                body += f', [ "," "{p.name}" ":" {_rule_name(t.name, p.name)} ]'
            out.append(f'{t.name}_call ::= "{t.name}" "(" {body} ")"')
            for p in t.params:
                out.append(f"{_rule_name(t.name, p.name)} ::= {_grammar_rhs(p.type)}")
            out.append("")
        out.append("STRING ::= '\"' { CHAR } '\"'")
        out.append('INT    ::= [ "-" ] DIGIT { DIGIT }')
        out.append('NUMBER ::= INT [ "." DIGIT { DIGIT } ]')
        out.append('BOOL   ::= "true" | "false"')
        return "\n".join(out)


def _grammar_rhs(t: TypeIR) -> str:
    if t.kind == TypeKind.ENUM:
        return " | ".join(json.dumps(str(v)) for v in t.enum_values)
    if t.kind == TypeKind.ARRAY:
        inner = _grammar_rhs(t.item) if t.item else "VALUE"
        return f'"[" [ {inner} {{ "," {inner} }} ] "]"'
    if t.kind == TypeKind.OBJECT:
        parts = [f'"{f.name}" ":" {_grammar_rhs(f.type)}' for f in t.fields]
        return '"{" ' + ' "," '.join(parts) + ' "}"'
    if t.kind == TypeKind.UNION:
        return " | ".join(_grammar_rhs(u) for u in t.union_of)
    return _term_for(t)


@register
class GBNFGrammar(SchemaRenderer):
    meta = FormatMeta(
        id="gbnf_grammar",
        name="GBNF constrained-decoding grammar (novel framing)",
        family="grammar",
        description=(
            "The llama.cpp GBNF dialect used for constrained decoding, shown "
            "to the model as the interface rather than enforced at sampling "
            "time. Same artefact, different channel."
        ),
        default_protocol="json_object",
        novel=True,
        real_world_origin="llama.cpp GBNF (normally used for decoding, not prompting)",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out = ["root ::= " + " | ".join(f"{t.name}-call" for t in tools), ""]
        for t in tools:
            props = []
            for p in t.params:
                rule = f'"\\"{p.name}\\":" {_gbnf_rhs(t.name, p)}'
                props.append(rule if p.required else f"({rule})?")
            joined = ' "," '.join(props)
            out.append(f'{t.name}-call ::= "{{\\"name\\":\\"{t.name}\\",\\"arguments\\":{{" {joined} "}}}}"')
            for p in t.params:
                out.append(f"{t.name}-{p.name} ::= {_gbnf_leaf(p.type)}")
            out.append("")
        out.append('string ::= "\\"" [^"]* "\\""')
        out.append('number ::= "-"? [0-9]+ ("." [0-9]+)?')
        out.append('boolean ::= "true" | "false"')
        return "\n".join(out)


def _gbnf_rhs(tool: str, p: ParamIR) -> str:
    return f"{tool}-{p.name}"


def _gbnf_leaf(t: TypeIR) -> str:
    if t.kind == TypeKind.ENUM:
        return " | ".join('"\\"' + str(v) + '\\""' for v in t.enum_values)
    if t.kind == TypeKind.ARRAY:
        inner = _gbnf_leaf(t.item) if t.item else "string"
        return f'"[" ({inner} ("," {inner})*)? "]"'
    if t.kind == TypeKind.OBJECT:
        parts = ['"\\"' + f.name + '\\":" ' + _gbnf_leaf(f.type) for f in t.fields]
        return '"{" ' + ' "," '.join(parts) + ' "}"'
    return {
        TypeKind.STRING: "string",
        TypeKind.INTEGER: "number",
        TypeKind.NUMBER: "number",
        TypeKind.BOOLEAN: "boolean",
    }.get(t.kind, "string")


@register
class RegexGrammar(SchemaRenderer):
    meta = FormatMeta(
        id="regex_spec",
        name="Regular expressions over call strings (novel)",
        family="grammar",
        description=(
            "One regex per tool matching every legal call string. Fully "
            "precise for flat tools, awkward for nested ones — which is "
            "exactly the trade-off we want measured."
        ),
        default_protocol="json_object",
        novel=True,
        supports_nesting=False,
        lossy=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            if opts.descriptions and t.description:
                out.append(f"# {t.description}")
            parts = []
            for p in t.params:
                frag = f'"{p.name}":{_regex_leaf(p.type)}'
                parts.append(frag if p.required else f"(?:{frag},?)?")
            out.append(f'^{{"name":"{t.name}","arguments":{{' + ",".join(parts) + r"\}\}$")
            out.append("")
        return "\n".join(out).rstrip()


def _regex_leaf(t: TypeIR) -> str:
    if t.kind == TypeKind.ENUM:
        return '"(?:' + "|".join(str(v) for v in t.enum_values) + ')"'
    if t.kind == TypeKind.INTEGER:
        return r"-?\d+"
    if t.kind == TypeKind.NUMBER:
        return r"-?\d+(?:\.\d+)?"
    if t.kind == TypeKind.BOOLEAN:
        return "(?:true|false)"
    if t.kind == TypeKind.ARRAY:
        return r"\[.*?\]"
    if t.kind == TypeKind.OBJECT:
        return r"\{.*?\}"
    return r'"[^"]*"'


@register
class TypedLambda(SchemaRenderer):
    meta = FormatMeta(
        id="typed_lambda",
        name="Typed lambda-calculus arrows (novel)",
        family="grammar",
        description=(
            "`get_weather : City × Unit? → Weather` in mathematical notation "
            "with product and sum types. The most abstract presentation in the "
            "study; nothing about it is code-like."
        ),
        default_protocol="json_object",
        novel=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            if opts.descriptions and t.description:
                out.append(f"-- {t.description}")
            dom = " × ".join(f"{p.name}:{_math_type(p.type)}" + ("" if p.required else "?") for p in t.params) or "1"
            ret = _math_type(t.returns) if (opts.returns and t.returns is not None) else "Result"
            out.append(f"{t.name} : {dom} → {ret}")
        return "\n".join(out)


def _math_type(t: TypeIR | None) -> str:
    if t is None:
        return "Unit"
    if t.kind == TypeKind.ARRAY:
        return f"List[{_math_type(t.item)}]"
    if t.kind == TypeKind.OBJECT:
        return "{" + " × ".join(f"{f.name}:{_math_type(f.type)}" for f in t.fields) + "}"
    if t.kind == TypeKind.ENUM:
        return "{" + " + ".join(str(v) for v in t.enum_values) + "}"
    if t.kind == TypeKind.UNION:
        return " + ".join(_math_type(u) for u in t.union_of)
    return {
        TypeKind.STRING: "Str",
        TypeKind.INTEGER: "Int",
        TypeKind.NUMBER: "Real",
        TypeKind.BOOLEAN: "Bool",
        TypeKind.NULL: "Unit",
    }.get(t.kind, "Any")


@register
class SymbolicCompressed(SchemaRenderer):
    meta = FormatMeta(
        id="symbolic_compressed",
        name="Symbolic ultra-compressed notation (novel)",
        family="grammar",
        description=(
            "A purpose-built shorthand: `weather!city:s?unit:{C,F}` where `!` "
            "starts required arguments, `?` starts optional ones, and types "
            "are single letters. Roughly the smallest faithful encoding we "
            "could design; it exists to anchor the low end of the token-cost "
            "axis."
        ),
        default_protocol="json_object",
        novel=True,
        compressed=True,
    )

    _LETTER = {
        TypeKind.STRING: "s",
        TypeKind.INTEGER: "i",
        TypeKind.NUMBER: "n",
        TypeKind.BOOLEAN: "b",
        TypeKind.ARRAY: "a",
        TypeKind.OBJECT: "o",
        TypeKind.NULL: "z",
        TypeKind.ANY: "*",
    }

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        lines = []
        for t in tools:
            s = t.name
            for p in t.params:
                s += ("!" if p.required else "?") + p.name + ":" + self._letter(p.type)
            lines.append(s)
        return "\n".join(lines)

    def _letter(self, t: TypeIR) -> str:
        if t.kind == TypeKind.ENUM:
            return "{" + ",".join(str(v) for v in t.enum_values) + "}"
        if t.kind == TypeKind.ARRAY:
            return "[" + self._letter(t.item) + "]" if t.item else "[*]"
        if t.kind == TypeKind.OBJECT:
            return "(" + ",".join(f"{f.name}:{self._letter(f.type)}" for f in t.fields) + ")"
        if t.kind == TypeKind.UNION:
            return "/".join(self._letter(u) for u in t.union_of)
        return self._LETTER.get(t.kind, "*")
