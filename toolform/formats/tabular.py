"""Tabular and line-oriented presentations.

Tables are the densest way to show many tools at once, which makes this family
the natural candidate to win at high tool counts. They also lose structure: a
table row cannot easily show a nested object, so nesting has to be flattened
or footnoted. That trade-off is exactly what the tool-count × complexity
interaction is about.
"""

from __future__ import annotations

import csv
import io

from ..ir import ToolIR, TypeIR, TypeKind
from .base import FormatMeta, RenderOptions, SchemaRenderer, register


def _flat_type(t: TypeIR) -> str:
    if t.kind == TypeKind.ARRAY:
        return f"{_flat_type(t.item)}[]" if t.item else "any[]"
    if t.kind == TypeKind.OBJECT:
        return "{" + ",".join(f"{f.name}:{_flat_type(f.type)}" for f in t.fields) + "}"
    if t.kind == TypeKind.ENUM:
        return "enum[" + "|".join(str(v) for v in t.enum_values) + "]"
    if t.kind == TypeKind.UNION:
        return "|".join(_flat_type(u) for u in t.union_of)
    return t.kind.value


def _rows(tools: list[ToolIR], opts: RenderOptions) -> list[list[str]]:
    rows = []
    for t in tools:
        for i, p in enumerate(t.params):
            # the tool's description on every row (the study's render), or on the
            # first row only: the rest of the row is the same
            show_doc = opts.descriptions and (i == 0 or not opts.tool_doc_once)
            rows.append(
                [
                    t.name,
                    p.name,
                    _flat_type(p.type),
                    "yes" if p.required else "no",
                    str(p.default) if (opts.defaults and p.default is not None) else "",
                    p.description if opts.descriptions else "",
                    t.description if show_doc else "",
                ]
            )
        if not t.params:
            rows.append([t.name, "", "", "", "", "", t.description if opts.descriptions else ""])
    return rows


HEADER = ["tool", "param", "type", "required", "default", "param_doc", "tool_doc"]


@register
class MarkdownTable(SchemaRenderer):
    meta = FormatMeta(
        id="markdown_table",
        name="Markdown table",
        family="tabular",
        description=(
            "One pipe-delimited row per parameter, with the tool name repeated. "
            "Very dense; nesting is flattened into a bracketed type string."
        ),
        default_protocol="json_object",
        real_world_origin="Markdown documentation tables",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        rows = _rows(tools, opts)
        cols = [i for i, h in enumerate(HEADER) if opts.descriptions or h not in ("param_doc", "tool_doc")]
        head = [HEADER[i] for i in cols]
        out = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] * len(head)) + "|"]
        for r in rows:
            out.append("| " + " | ".join(_esc_md(r[i]) for i in cols) + " |")
        return "\n".join(out)


def _esc_md(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


@register
class CSVTools(SchemaRenderer):
    meta = FormatMeta(
        id="csv",
        name="CSV table",
        family="tabular",
        description="Comma-separated rows with a header line. No layout at all.",
        default_protocol="json_object",
        real_world_origin="CSV",
        compressed=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        cols = [i for i, h in enumerate(HEADER) if opts.descriptions or h not in ("param_doc", "tool_doc")]
        w.writerow([HEADER[i] for i in cols])
        for r in _rows(tools, opts):
            w.writerow([r[i] for i in cols])
        return buf.getvalue().rstrip()


@register
class TSVTools(SchemaRenderer):
    meta = FormatMeta(
        id="tsv",
        name="TSV table",
        family="tabular",
        description="Tab-separated variant of the CSV table: usually a few tokens cheaper.",
        default_protocol="json_object",
        real_world_origin="TSV",
        compressed=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        cols = [i for i, h in enumerate(HEADER) if opts.descriptions or h not in ("param_doc", "tool_doc")]
        lines = ["\t".join(HEADER[i] for i in cols)]
        for r in _rows(tools, opts):
            lines.append("\t".join(str(r[i]).replace("\t", " ") for i in cols))
        return "\n".join(lines)


@register
class AsciiTable(SchemaRenderer):
    meta = FormatMeta(
        id="ascii_table",
        name="Aligned ASCII table",
        family="tabular",
        description=(
            "Box-drawn, column-aligned table. Costs padding tokens but is the most visually parseable tabular variant."
        ),
        default_protocol="json_object",
        real_world_origin="Console table output",
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        cols = [i for i, h in enumerate(HEADER) if opts.descriptions or h not in ("param_doc", "tool_doc")]
        rows = [[HEADER[i] for i in cols]] + [[str(r[i]) for i in cols] for r in _rows(tools, opts)]
        widths = [max(len(r[c]) for r in rows) for c in range(len(cols))]
        sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
        out = [sep]
        for n, r in enumerate(rows):
            out.append("| " + " | ".join(v.ljust(widths[i]) for i, v in enumerate(r)) + " |")
            if n == 0:
                out.append(sep)
        out.append(sep)
        return "\n".join(out)


@register
class KeyValueLines(SchemaRenderer):
    meta = FormatMeta(
        id="key_value_lines",
        name="Key-value lines",
        family="tabular",
        description=(
            "`tool.param: type (required) # doc`, one leaf per line. No "
            "delimiters, no nesting punctuation — the flattest readable form."
        ),
        default_protocol="key_value_call",
        real_world_origin="Java properties / dotenv style listings",
        compressed=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            if opts.descriptions and t.description:
                out.append(f"# {t.name} — {t.description}")
            for p in t.params:
                req = "required" if p.required else "optional"
                line = f"{t.name}.{p.name}: {_flat_type(p.type)} ({req})"
                if opts.defaults and p.default is not None:
                    line += f" = {p.default}"
                if opts.descriptions and p.description:
                    line += f"  # {p.description}"
                out.append(line)
        return "\n".join(out)


@register
class ColonCompact(SchemaRenderer):
    meta = FormatMeta(
        id="compact_signature_lines",
        name="Compact one-line signatures (novel)",
        family="tabular",
        description=(
            "`tool_name: req_a:str req_b:int [opt_c:bool]` — one line per tool, "
            "square brackets for optional. Roughly the cheapest presentation "
            "that still names every argument and its type."
        ),
        default_protocol="json_object",
        novel=True,
        compressed=True,
        lossy=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = []
        for t in tools:
            bits = []
            for p in t.params:
                s = f"{p.name}:{_abbrev_type(p.type)}"
                bits.append(s if p.required else f"[{s}]")
            line = f"{t.name}: " + " ".join(bits)
            if opts.descriptions and t.description:
                line += f"  // {t.description}"
            out.append(line)
        return "\n".join(out)


_ABBREV = {
    TypeKind.STRING: "str",
    TypeKind.INTEGER: "int",
    TypeKind.NUMBER: "num",
    TypeKind.BOOLEAN: "bool",
    TypeKind.OBJECT: "obj",
    TypeKind.ANY: "any",
    TypeKind.NULL: "null",
}


def _abbrev_type(t: TypeIR) -> str:
    if t.kind == TypeKind.ARRAY:
        return f"[{_abbrev_type(t.item)}]" if t.item else "[any]"
    if t.kind == TypeKind.ENUM:
        return "{" + "|".join(str(v) for v in t.enum_values) + "}"
    if t.kind == TypeKind.UNION:
        return "|".join(_abbrev_type(u) for u in t.union_of)
    if t.kind == TypeKind.OBJECT:
        return "{" + ",".join(f"{f.name}:{_abbrev_type(f.type)}" for f in t.fields) + "}"
    return _ABBREV.get(t.kind, "any")


@register
class TwoColumnIndex(SchemaRenderer):
    meta = FormatMeta(
        id="two_stage_index",
        name="Two-stage index then detail (novel)",
        family="tabular",
        description=(
            "First a one-line index of every tool name and purpose, then the "
            "full schemas below. Gives the model a cheap routing pass before "
            "it has to read any schema — a direct test of whether tool-count "
            "decay is a search problem or a reading problem."
        ),
        default_protocol="json_object",
        novel=True,
    )

    def render_tools(self, tools: list[ToolIR], opts: RenderOptions) -> str:
        out: list[str] = ["INDEX (tool -> purpose)"]
        for t in tools:
            purpose = t.description.split(".")[0] if opts.descriptions and t.description else ""
            out.append(f"  {t.name}: {purpose}")
        out.append("")
        out.append("DETAIL")
        for t in tools:
            out.append(f"  {t.name}")
            for p in t.params:
                req = "required" if p.required else "optional"
                line = f"    {p.name} ({_flat_type(p.type)}, {req})"
                if opts.descriptions and p.description:
                    line += f": {p.description}"
                out.append(line)
        return "\n".join(out)
