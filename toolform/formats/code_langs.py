"""Source-language signature formats.

Fourteen more programming languages, each rendering the same tools as a
function/method signature with that language's idiomatic doc comment. The
point is not that anyone ships tools as Zig headers — it is that language
identity is a clean way to vary *surface familiarity* while holding semantics
fixed. If accuracy tracks how much of a language a model saw in pretraining,
that is a result about pretraining exposure, not about schemas.

Every renderer here is driven by :data:`toolform.formats.common.LANG_TYPES`,
so adding a language is a small declarative block rather than new logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..ir import ToolIR, TypeKind
from .base import FormatMeta, RenderOptions, SchemaRenderer, register
from .common import camel, js_value, lang, ordered_params, pascal


@dataclass(frozen=True)
class LangStyle:
    """Layout rules for a C-like or ML-like signature language."""

    language: str
    line_comment: str = "//"
    doc_open: str | None = None
    doc_line: str | None = None
    doc_close: str | None = None
    fn_keyword: str = "func"
    # f(name, args, ret) -> signature line
    signature: Callable[[str, str, str], str] | None = None
    param_sep: str = ", "
    param_fmt: str = "{name}: {type}"
    optional_marker: str = ""
    name_style: str = "snake"  # snake | camel | pascal
    terminator: str = ";"


def _fmt_name(name: str, style: str) -> str:
    if style == "camel":
        return camel(name)
    if style == "pascal":
        return pascal(name)
    return name


def _render_lang(tools: list[ToolIR], opts: RenderOptions, style: LangStyle) -> str:
    spec = lang(style.language)
    out: list[str] = []
    for t in tools:
        if opts.descriptions and (t.description or any(p.description for p in t.params)):
            if style.doc_open is not None:
                out.append(style.doc_open)
                if t.description:
                    out.append(f"{style.doc_line} {t.description}")
                for p in t.params:
                    if p.description:
                        out.append(f"{style.doc_line} @param {p.name} {p.description}")
                if opts.returns and t.returns_description:
                    out.append(f"{style.doc_line} @return {t.returns_description}")
                if style.doc_close:
                    out.append(style.doc_close)
            else:
                if t.description:
                    out.append(f"{style.line_comment} {t.description}")
                for p in t.params:
                    if p.description:
                        out.append(f"{style.line_comment} {p.name}: {p.description}")

        params = []
        for p in ordered_params(t):
            ty = spec.render(p.type)
            if not p.required and spec.optional is not None:
                ty = spec.optional(ty)
            params.append(
                style.param_fmt.format(name=_fmt_name(p.name, style.name_style), type=ty)
                + (style.optional_marker if not p.required else "")
            )
        args = style.param_sep.join(params)
        ret = spec.render(t.returns) if (opts.returns and t.returns is not None) else spec.any_type
        fname = _fmt_name(t.name, style.name_style)
        if style.signature is not None:
            out.append(style.signature(fname, args, ret) + style.terminator)
        else:
            out.append(f"{style.fn_keyword} {fname}({args}) {ret}{style.terminator}")
        out.append("")
    return "\n".join(out).rstrip()


def _make(
    fmt_id: str,
    name: str,
    description: str,
    origin: str,
    style: LangStyle,
    *,
    protocol: str = "json_object",
    novel: bool = False,
    lossy: bool = False,
) -> type[SchemaRenderer]:
    class _Renderer(SchemaRenderer):
        meta = FormatMeta(
            id=fmt_id,
            name=name,
            family="code",
            description=description,
            default_protocol=protocol,
            real_world_origin=origin,
            novel=novel,
            lossy=lossy,
        )
        _style = style

        def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
            return _render_lang(tools, opts, self._style)

    _Renderer.__name__ = "".join(w.capitalize() for w in fmt_id.split("_")) + "Renderer"
    return register(_Renderer)


# --------------------------------------------------------------------------- #
# C-family
# --------------------------------------------------------------------------- #

GoSignatures = _make(
    "go_signature",
    "Go function signatures",
    "Idiomatic Go: exported funcs with `// Name does ...` doc comments and explicit return types.",
    "Go",
    LangStyle(
        language="go",
        line_comment="//",
        signature=lambda n, a, r: f"func {n}({a}) ({r}, error)",
        param_fmt="{name} {type}",
        name_style="pascal",
        terminator="",
    ),
)

RustSignatures = _make(
    "rust_signature",
    "Rust function signatures with serde structs",
    "Rust `pub fn` declarations with `///` doc comments and Option<T> for "
    "optional arguments — types carry optionality instead of a separate flag.",
    "Rust",
    LangStyle(
        language="rust",
        line_comment="///",
        signature=lambda n, a, r: f"pub fn {n}({a}) -> Result<{r}, ToolError>",
        param_fmt="{name}: {type}",
        terminator=";",
    ),
)

JavaSignatures = _make(
    "java_signature",
    "Java interface methods with Javadoc",
    "Java method declarations inside an interface, documented with Javadoc "
    "tags. The most ceremonious presentation in the study.",
    "Java",
    LangStyle(
        language="java",
        doc_open="/**",
        doc_line=" *",
        doc_close=" */",
        signature=lambda n, a, r: f"public {r} {n}({a})",
        param_fmt="{type} {name}",
        name_style="camel",
        terminator=";",
    ),
)

KotlinSignatures = _make(
    "kotlin_signature",
    "Kotlin function signatures",
    "Kotlin `fun` declarations with nullable types for optional arguments and KDoc comments.",
    "Kotlin",
    LangStyle(
        language="kotlin",
        doc_open="/**",
        doc_line=" *",
        doc_close=" */",
        signature=lambda n, a, r: f"fun {n}({a}): {r}",
        param_fmt="{name}: {type}",
        name_style="camel",
        terminator="",
    ),
)

SwiftSignatures = _make(
    "swift_signature",
    "Swift function signatures",
    "Swift `func` declarations with labelled arguments — argument labels give "
    "the model an extra naming cue that most languages lack.",
    "Swift",
    LangStyle(
        language="swift",
        line_comment="///",
        signature=lambda n, a, r: f"func {n}({a}) -> {r}",
        param_fmt="{name}: {type}",
        name_style="camel",
        terminator="",
    ),
)

CSharpSignatures = _make(
    "csharp_signature",
    "C# method signatures with XML doc",
    "C# methods documented with `<summary>`/`<param>` XML comments — a doc style that is itself markup.",
    "C#",
    LangStyle(
        language="csharp",
        doc_open="/// <summary>",
        doc_line="///",
        doc_close="/// </summary>",
        signature=lambda n, a, r: f"public {r} {n}({a})",
        param_fmt="{type} {name}",
        name_style="pascal",
        terminator=";",
    ),
)

CHeader = _make(
    "c_header",
    "C header declarations",
    "Plain C prototypes with block comments. Cannot express optionality or "
    "enums natively, so it is our lower bound on type expressiveness.",
    "C",
    LangStyle(
        language="c",
        doc_open="/*",
        doc_line=" *",
        doc_close=" */",
        signature=lambda n, a, r: f"{r} {n}({a})",
        param_fmt="{type} {name}",
        terminator=";",
    ),
    lossy=True,
)

CppSignatures = _make(
    "cpp_signature",
    "C++ declarations with std types",
    "C++ prototypes using std::optional and std::variant, so optionality and "
    "unions are in the type rather than in prose.",
    "C++",
    LangStyle(
        language="cpp",
        doc_open="/**",
        doc_line=" *",
        doc_close=" */",
        signature=lambda n, a, r: f"{r} {n}({a})",
        param_fmt="{type} {name}",
        terminator=";",
    ),
)


# --------------------------------------------------------------------------- #
# ML / functional family
# --------------------------------------------------------------------------- #


@register
class HaskellRenderer(SchemaRenderer):
    """Haskell needs a curried layout, so it overrides the generic renderer."""

    meta = FormatMeta(
        id="haskell_curried",
        name="Haskell curried signatures",
        family="code",
        description=(
            "`toolName :: ArgType1 -> ArgType2 -> IO Result` with named-argument "
            "hints only in comments. Tests whether models can bind arguments "
            "positionally when the interface gives no keyword slots."
        ),
        default_protocol="json_object",
        real_world_origin="Haskell",
        lossy=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        spec = lang("haskell")
        out: list[str] = []
        for t in tools:
            if opts.descriptions and t.description:
                out.append(f"-- | {t.description}")
            for p in t.params:
                if opts.descriptions and p.description:
                    out.append(f"--   {p.name}: {p.description}")
            types = []
            for p in t.params:
                ty = spec.render(p.type)
                types.append(f"Maybe {ty}" if not p.required else ty)
            ret = spec.render(t.returns) if (opts.returns and t.returns is not None) else "Value"
            chain = " -> ".join(types + [f"IO {ret}"])
            out.append(f"{camel(t.name)} :: {chain}")
            out.append("")
        return "\n".join(out).rstrip()


OCamlSignatures = _make(
    "ocaml_signature",
    "OCaml val declarations",
    "OCaml `val` declarations with labelled arguments (~name:type), which keeps names while staying in ML syntax.",
    "OCaml",
    LangStyle(
        language="ocaml",
        line_comment="(*",
        signature=lambda n, a, r: f"val {n} : {a} -> {r}",
        param_sep=" -> ",
        param_fmt="~{name}:{type}",
        terminator="",
    ),
)

ScalaSignatures = _make(
    "scala_signature",
    "Scala method signatures",
    "Scala `def` declarations with Option[T] and default values.",
    "Scala",
    LangStyle(
        language="scala",
        doc_open="/**",
        doc_line=" *",
        doc_close=" */",
        signature=lambda n, a, r: f"def {n}({a}): {r}",
        param_fmt="{name}: {type}",
        name_style="camel",
        terminator="",
    ),
)

ElixirSignatures = _make(
    "elixir_signature",
    "Elixir @spec declarations",
    "Elixir specs with @doc strings — documentation is a first-class language construct here rather than a comment.",
    "Elixir",
    LangStyle(
        language="elixir",
        line_comment="#",
        signature=lambda n, a, r: f"@spec {n}({a}) :: {r}",
        param_fmt="{type}",
        terminator="",
    ),
    lossy=True,
)

JuliaSignatures = _make(
    "julia_signature",
    "Julia function signatures",
    "Julia declarations with keyword arguments after a semicolon, which maps cleanly onto required/optional.",
    "Julia",
    LangStyle(
        language="julia",
        line_comment="#",
        signature=lambda n, a, r: f"function {n}({a})::{r}",
        param_fmt="{name}::{type}",
        terminator="",
    ),
)


# --------------------------------------------------------------------------- #
# scripting family
# --------------------------------------------------------------------------- #

RubySignatures = _make(
    "ruby_signature",
    "Ruby method signatures (RBS-style types)",
    "Ruby `def` lines with an RBS type comment above them.",
    "Ruby / RBS",
    LangStyle(
        language="ruby",
        line_comment="#",
        signature=lambda n, a, r: f"def {n}({a}) # => {r}",
        param_fmt="{name}:",
        terminator="",
    ),
    lossy=True,
)

PHPSignatures = _make(
    "php_signature",
    "PHP function signatures with PHPDoc",
    "PHP declarations with PHPDoc @param annotations carrying the real types.",
    "PHP",
    LangStyle(
        language="php",
        doc_open="/**",
        doc_line=" *",
        doc_close=" */",
        signature=lambda n, a, r: f"function {n}({a}): {r}",
        param_fmt="{type} ${name}",
        terminator=";",
    ),
)

LuaSignatures = _make(
    "lua_signature",
    "Lua function declarations with LDoc",
    "Lua functions annotated with LDoc `---@param` lines. Everything is a "
    "table, so structure lives entirely in the annotations.",
    "Lua / LDoc",
    LangStyle(
        language="lua",
        line_comment="---",
        signature=lambda n, a, r: f"function {n}({a}) end",
        param_fmt="{name}",
        terminator="",
    ),
    lossy=True,
)

ZigSignatures = _make(
    "zig_signature",
    "Zig function declarations",
    "Zig `pub fn` with optional pointers (`?T`) and error unions.",
    "Zig",
    LangStyle(
        language="zig",
        line_comment="///",
        signature=lambda n, a, r: f"pub fn {n}({a}) !{r}",
        param_fmt="{name}: {type}",
        terminator="",
    ),
)

RSignatures = _make(
    "r_signature",
    "R function signatures with roxygen",
    "R functions documented with roxygen2 `#' @param` blocks.",
    "R / roxygen2",
    LangStyle(
        language="r",
        line_comment="#'",
        signature=lambda n, a, r: f"{n} <- function({a})",
        param_fmt="{name}",
        terminator="",
    ),
    lossy=True,
)


@register
class MatlabSignatures(SchemaRenderer):
    meta = FormatMeta(
        id="matlab_signature",
        name="MATLAB function signatures",
        family="code",
        description=(
            "MATLAB `function out = name(args)` with an `arguments` validation "
            "block — an unusual but real way to declare types and defaults."
        ),
        default_protocol="json_object",
        real_world_origin="MATLAB",
        lossy=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            args = ", ".join(p.name for p in t.params)
            out.append(f"function result = {t.name}({args})")
            if opts.descriptions and t.description:
                out.append(f"% {t.description}")
            out.append("    arguments")
            for p in t.params:
                ty = {
                    TypeKind.STRING: "string",
                    TypeKind.INTEGER: "double",
                    TypeKind.NUMBER: "double",
                    TypeKind.BOOLEAN: "logical",
                    TypeKind.ARRAY: "cell",
                    TypeKind.OBJECT: "struct",
                }.get(p.type.kind, "string")
                extra = ""
                if p.type.kind == TypeKind.ENUM:
                    extra = " {mustBeMember(" + p.name + ", [" + ", ".join(f'"{v}"' for v in p.type.enum_values) + "])}"
                    ty = "string"
                default = ""
                if not p.required and opts.defaults and p.default is not None:
                    default = f" = {js_value(p.default)}"
                comment = f"  % {p.description}" if opts.descriptions and p.description else ""
                out.append(f"        {p.name} {ty}{extra}{default}{comment}")
            out.append("    end")
            out.append("end")
            out.append("")
        return "\n".join(out).rstrip()


@register
class SQLFunctions(SchemaRenderer):
    meta = FormatMeta(
        id="sql_udf",
        name="SQL user-defined function declarations",
        family="code",
        description=(
            "`CREATE FUNCTION name(arg TYPE DEFAULT x) RETURNS ...` with "
            "COMMENT ON statements for the prose. Tools as database functions."
        ),
        default_protocol="sql_call",
        real_world_origin="PostgreSQL CREATE FUNCTION",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        spec = lang("sql")
        out: list[str] = []
        for t in tools:
            args = []
            for p in t.params:
                ty = spec.render(p.type)
                d = ""
                if not p.required and opts.defaults and p.default is not None:
                    d = f" DEFAULT {_sql_lit(p.default)}"
                elif not p.required:
                    d = " DEFAULT NULL"
                args.append(f"{p.name} {ty}{d}")
            ret = spec.render(t.returns) if (opts.returns and t.returns is not None) else "JSONB"
            out.append(f"CREATE FUNCTION {t.name}(")
            out.append(",\n".join(f"    {a}" for a in args))
            out.append(f") RETURNS {ret};")
            if opts.descriptions and t.description:
                out.append(f"COMMENT ON FUNCTION {t.name} IS '{t.description}';")
                for p in t.params:
                    if p.description:
                        out.append(f"-- {p.name}: {p.description}")
            out.append("")
        return "\n".join(out).rstrip()


def _sql_lit(v) -> str:
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    return str(v)


@register
class BashFunctions(SchemaRenderer):
    meta = FormatMeta(
        id="bash_function",
        name="Bash function stubs with usage comments",
        family="code",
        description=(
            "Shell functions with a usage line and `local` variable "
            "assignments. Everything is a string here, which makes it the "
            "weakest type channel of any code format."
        ),
        default_protocol="cli_call",
        real_world_origin="POSIX shell",
        lossy=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            if opts.descriptions and t.description:
                out.append(f"# {t.description}")
            flags = " ".join(
                (f"--{p.name} <{p.type.kind.value}>" if p.required else f"[--{p.name} <{p.type.kind.value}>]")
                for p in t.params
            )
            out.append(f"# usage: {t.name} {flags}")
            for p in t.params:
                if opts.descriptions and p.description:
                    out.append(f"#   --{p.name}: {p.description}")
            out.append(f"{t.name}() {{")
            out.append("  :")
            out.append("}")
            out.append("")
        return "\n".join(out).rstrip()
