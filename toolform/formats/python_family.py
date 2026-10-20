"""Python-flavoured tool declarations.

Python stubs are the second-most-recommended alternative to JSON Schema, and
LLMs have seen enormous amounts of Python. The variants below differ in where
the documentation lives (docstring style), whether validation types are
explicit (pydantic), and whether the interface is a function or a CLI parser.
"""

from __future__ import annotations

from ..ir import ParamIR, ToolIR, TypeIR, TypeKind
from .base import FormatMeta, RenderOptions, SchemaRenderer, register
from .common import lang, ordered_params, pascal, py_value

PY = lang("python")


def _py_type(t: TypeIR, tool: ToolIR | None = None, p: ParamIR | None = None) -> str:
    if t.kind == TypeKind.OBJECT and t.fields:
        inner = ", ".join(f'"{f.name}": {_py_type(f.type)}' for f in t.fields)
        return "dict[str, Any]" if not inner else "dict[str, Any]"
    if t.kind == TypeKind.ARRAY and t.item is not None:
        return f"list[{_py_type(t.item)}]"
    if t.kind == TypeKind.ENUM:
        return "Literal[" + ", ".join(py_value(v) for v in t.enum_values) + "]"
    if t.kind == TypeKind.UNION:
        return " | ".join(_py_type(u) for u in t.union_of)
    return PY.render(t)


def _signature(t: ToolIR, opts: RenderOptions, *, self_arg: bool = False) -> str:
    parts: list[str] = ["self"] if self_arg else []
    for p in ordered_params(t):
        ann = _py_type(p.type, t, p)
        if p.required:
            parts.append(f"{p.name}: {ann}")
        else:
            default = py_value(p.default) if opts.defaults else "None"
            parts.append(f"{p.name}: {ann} = {default}")
    ret = _py_type(t.returns) if (opts.returns and t.returns is not None) else "Any"
    return f"def {t.name}({', '.join(parts)}) -> {ret}:"


def _nested_note(p: ParamIR) -> str:
    """Describe an object parameter's inner shape in one line."""
    t = p.type
    if t.kind == TypeKind.OBJECT and t.fields:
        return (
            " Keys: "
            + ", ".join(f"{f.name} ({f.type.kind.value}{'' if f.required else ', optional'})" for f in t.fields)
            + "."
        )
    if t.kind == TypeKind.ARRAY and t.item is not None and t.item.kind == TypeKind.OBJECT:
        return " Each item has keys: " + ", ".join(f.name for f in t.item.fields) + "."
    return ""


@register
class PythonGoogleDocstring(SchemaRenderer):
    meta = FormatMeta(
        id="python_stub",
        name="Python function stubs (Google docstrings)",
        family="code",
        description=(
            "`def tool(arg: type = default) -> Return:` with a Google-style "
            "docstring. The single most familiar shape in pretraining data."
        ),
        default_protocol="python_call",
        real_world_origin="Python / Google docstring convention; LangChain @tool",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            out.append(_signature(t, opts))
            if opts.descriptions:
                out.append('    """' + (t.description or t.name))
                if t.params:
                    out.append("")
                    out.append("    Args:")
                    for p in t.params:
                        req = "" if p.required else ", optional"
                        note = _nested_note(p)
                        out.append(f"        {p.name} ({_py_type(p.type)}{req}): {p.description}{note}".rstrip())
                if opts.returns and (t.returns is not None or t.returns_description):
                    out.append("")
                    out.append("    Returns:")
                    out.append(f"        {t.returns_description or 'Result of the call.'}")
                out.append('    """')
            out.append("    ...")
            out.append("")
        return "\n".join(out).rstrip()


@register
class PythonNumpyDocstring(SchemaRenderer):
    meta = FormatMeta(
        id="python_stub_numpy",
        name="Python function stubs (NumPy docstrings)",
        family="code",
        description=(
            "Same stubs with NumPy-style section headers and underlines. "
            "Controls for docstring dialect inside the same language."
        ),
        default_protocol="python_call",
        real_world_origin="NumPy docstring convention",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            out.append(_signature(t, opts))
            if opts.descriptions:
                out.append('    """')
                out.append(f"    {t.description or t.name}")
                if t.params:
                    out.append("")
                    out.append("    Parameters")
                    out.append("    ----------")
                    for p in t.params:
                        req = "" if p.required else ", optional"
                        out.append(f"    {p.name} : {_py_type(p.type)}{req}")
                        if p.description:
                            out.append(f"        {p.description}{_nested_note(p)}")
                if opts.returns:
                    out.append("")
                    out.append("    Returns")
                    out.append("    -------")
                    out.append(f"    {_py_type(t.returns) if t.returns else 'Any'}")
                    if t.returns_description:
                        out.append(f"        {t.returns_description}")
                out.append('    """')
            out.append("    ...")
            out.append("")
        return "\n".join(out).rstrip()


@register
class PythonSignatureOnly(SchemaRenderer):
    meta = FormatMeta(
        id="python_signature_only",
        name="Python signatures only",
        family="code",
        description=(
            "One `def` line per tool, no docstring at all. The Python arm of "
            "the descriptions-off comparison, kept as its own format so the "
            "cheap variant is directly comparable."
        ),
        default_protocol="python_call",
        real_world_origin="Python",
        compressed=True,
        lossy=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        return "\n".join(_signature(t, opts)[:-1] for t in tools)


@register
class PythonPydantic(SchemaRenderer):
    meta = FormatMeta(
        id="python_pydantic",
        name="Pydantic models",
        family="code",
        description=(
            "One `BaseModel` per tool with `Field(...)` descriptions and "
            "validation constraints. The shape most Python agent frameworks "
            "actually build schemas from."
        ),
        default_protocol="json_object",
        real_world_origin="Pydantic v2; LangChain / Instructor tool args",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = [
            "from pydantic import BaseModel, Field",
            "from typing import Any, Literal",
            "",
        ]
        for t in tools:
            cls = pascal(t.name)
            out.append(f"class {cls}(BaseModel):")
            if opts.descriptions and t.description:
                out.append(f'    """{t.description}"""')
            if not t.params:
                out.append("    pass")
            for p in t.params:
                ann = _py_type(p.type)
                field_bits = []
                if p.required:
                    field_bits.append("...")
                else:
                    field_bits.append(py_value(p.default) if opts.defaults else "None")
                if opts.descriptions and p.description:
                    field_bits.append(f"description={py_value(p.description)}")
                if opts.constraints:
                    field_bits.extend(_pydantic_constraints(p.type))
                out.append(f"    {p.name}: {ann} = Field({', '.join(field_bits)})")
            out.append("")
            out.append(f"def {t.name}(args: {cls}) -> Any: ...")
            out.append("")
        return "\n".join(out).rstrip()


def _pydantic_constraints(t: TypeIR) -> list[str]:
    c = t.constraints
    bits = []
    if c.minimum is not None:
        bits.append(f"ge={c.minimum}")
    if c.maximum is not None:
        bits.append(f"le={c.maximum}")
    if c.min_length is not None:
        bits.append(f"min_length={c.min_length}")
    if c.max_length is not None:
        bits.append(f"max_length={c.max_length}")
    if c.pattern:
        bits.append(f"pattern={py_value(c.pattern)}")
    return bits


@register
class PythonDataclass(SchemaRenderer):
    meta = FormatMeta(
        id="python_dataclass",
        name="Python dataclasses",
        family="code",
        description=(
            "Argument bundles as `@dataclass` definitions plus a call function. "
            "Stdlib-only counterpart to the pydantic variant."
        ),
        default_protocol="json_object",
        real_world_origin="Python dataclasses",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = ["from dataclasses import dataclass", "from typing import Any, Literal", ""]
        for t in tools:
            cls = pascal(t.name) + "Args"
            out.append("@dataclass")
            out.append(f"class {cls}:")
            if opts.descriptions and t.description:
                out.append(f'    """{t.description}"""')
            if not t.params:
                out.append("    pass")
            for p in t.params:
                ann = _py_type(p.type)
                if p.required:
                    out.append(f"    {p.name}: {ann}")
                else:
                    out.append(f"    {p.name}: {ann} = {py_value(p.default) if opts.defaults else 'None'}")
                if opts.descriptions and p.description:
                    out.append(f"    # {p.description}")
            out.append("")
        return "\n".join(out).rstrip()


@register
class PythonArgparse(SchemaRenderer):
    meta = FormatMeta(
        id="python_argparse",
        name="argparse parser construction (novel)",
        family="code",
        description=(
            "Each tool shown as the argparse code that would define its "
            "command line: add_argument calls carrying type, choices, default "
            "and help. A code-shaped way to state a schema that no agent "
            "framework uses today."
        ),
        default_protocol="cli_call",
        novel=True,
        real_world_origin="",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = ["import argparse", ""]
        for t in tools:
            out.append(f"{t.name}_parser = argparse.ArgumentParser(")
            out.append(f'    prog="{t.name}",')
            if opts.descriptions and t.description:
                out.append(f"    description={py_value(t.description)},")
            out.append(")")
            for p in t.params:
                bits = [f'"--{p.name.replace("_", "-")}"']
                if p.type.kind == TypeKind.ENUM:
                    bits.append("choices=[" + ", ".join(py_value(v) for v in p.type.enum_values) + "]")
                elif p.type.kind == TypeKind.BOOLEAN:
                    bits.append('action="store_true"')
                elif p.type.kind == TypeKind.ARRAY:
                    bits.append('nargs="+"')
                    if p.type.item is not None:
                        bits.append(f"type={_argparse_type(p.type.item)}")
                else:
                    bits.append(f"type={_argparse_type(p.type)}")
                bits.append(f"required={p.required}")
                if opts.defaults and p.default is not None:
                    bits.append(f"default={py_value(p.default)}")
                if opts.descriptions and p.description:
                    bits.append(f"help={py_value(p.description)}")
                out.append(f"{t.name}_parser.add_argument({', '.join(bits)})")
            out.append("")
        return "\n".join(out).rstrip()


def _argparse_type(t: TypeIR) -> str:
    return {
        TypeKind.INTEGER: "int",
        TypeKind.NUMBER: "float",
        TypeKind.BOOLEAN: "bool",
    }.get(t.kind, "str")


@register
class PythonCallableProtocol(SchemaRenderer):
    meta = FormatMeta(
        id="python_protocol",
        name="typing.Protocol tool interface",
        family="code",
        description=(
            "All tools as methods of one `class Tools(Protocol)`. Puts the "
            "whole universe in a single named scope instead of a flat list."
        ),
        default_protocol="python_call",
        real_world_origin="Python typing.Protocol",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out = ["from typing import Any, Literal, Protocol", "", "class Tools(Protocol):"]
        for t in tools:
            out.append("    " + _signature(t, opts, self_arg=True))
            if opts.descriptions and t.description:
                out.append(f'        """{t.description}"""')
                for p in t.params:
                    if p.description:
                        out.append(f"        # {p.name}: {p.description}")
            out.append("        ...")
            out.append("")
        return "\n".join(out).rstrip()
