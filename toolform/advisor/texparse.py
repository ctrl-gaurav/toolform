"""Read the paper's generated LaTeX tables. Used only by the evidence build.

The tables are machine-written by the owner's scripts, so their cell forms are
few and regular: colour commands, bold, a rank marker, thousands written as
``1{,}315.4``, minus signs as ``$-$`` and intervals as ``[lo, hi]`` in a small
font. :func:`clean_cell` turns one cell into its text, first number, interval
and bold flag.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TexCell:
    """One cleaned table cell."""

    text: str
    value: float | None
    interval: tuple[float, float] | None
    bold: bool
    raw: str = ""

    @property
    def rank(self) -> int | None:
        """The ``\\rank{n}`` marker of the cell, if any."""
        m = re.search(r"\\rank\{(\d+)\}", self.raw)
        return int(m.group(1)) if m else None


@dataclass
class TexRow:
    """One table row and the title of the block it sits in."""

    cells: list[TexCell]
    block: str = ""
    raw: str = field(default="", repr=False)

    def texts(self) -> list[str]:
        return [c.text for c in self.cells]


def strip_comments(tex: str) -> str:
    """Remove ``%`` comments (an escaped ``\\%`` is kept)."""
    return "\n".join(re.sub(r"(?<!\\)%.*$", "", line) for line in tex.splitlines())


def _brace_arg(s: str, i: int) -> tuple[str, int]:
    """The content of the brace group starting at ``s[i] == '{'`` and the index after it."""
    if i >= len(s) or s[i] != "{":
        return "", i
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "{" and (j == 0 or s[j - 1] != "\\"):
            depth += 1
        elif s[j] == "}" and (j == 0 or s[j - 1] != "\\"):
            depth -= 1
            if depth == 0:
                return s[i + 1 : j], j + 1
    return s[i + 1 :], len(s)


def _drop_command(s: str, name: str, nargs: int, keep: int | None = None) -> str:
    """Remove ``\\name{..}{..}``; with ``keep``, replace it by that argument's content."""
    out = []
    i = 0
    pat = "\\" + name
    while True:
        j = s.find(pat, i)
        if j < 0:
            out.append(s[i:])
            break
        after = j + len(pat)
        if after < len(s) and (s[after].isalpha()):
            out.append(s[i:after])
            i = after
            continue
        out.append(s[i:j])
        k = after
        args = []
        for _ in range(nargs):
            while k < len(s) and s[k] == " ":
                k += 1
            arg, k = _brace_arg(s, k)
            args.append(arg)
        if keep is not None and keep < len(args):
            out.append(args[keep])
        i = k
    return "".join(out)


_NUM = r"[+-]?\d+(?:\.\d+)?"
_INTERVAL = re.compile(r"\[\s*(" + _NUM + r")\s*,\s*(" + _NUM + r")\s*\]")


def _clean_text(raw: str) -> tuple[str, bool]:
    s = raw
    bold = "\\textbf" in s or "\\bfseries" in s
    s = _drop_command(s, "cellcolor", 1)
    s = _drop_command(s, "rowcolor", 1)
    s = _drop_command(s, "rank", 1)
    s = _drop_command(s, "fontsize", 2)
    s = _drop_command(s, "textcolor", 2, keep=1)
    s = _drop_command(s, "rule", 2)
    s = _drop_command(s, "hspace", 1)
    for cmd in ("textbf", "texttt", "textit", "emph", "textsc", "mbox"):
        s = _drop_command(s, cmd, 1, keep=0)
    s = s.replace("$-$", "-").replace("$+$", "+").replace("\\,", "").replace("{,}", "")
    s = s.replace("\\%", "").replace("$", "").replace("\\_", "_").replace("\\&", "&")
    s = s.replace("--", "-") if re.search(r"\d--\d", s) else s
    s = re.sub(
        r"\\(?:selectfont|scriptsize|footnotesize|small|sffamily|bfseries|itshape|enspace|quad|"
        r"faServer|faCloud|faLock|centering|raggedright)",
        " ",
        s,
    )
    s = re.sub(r"\\[A-Za-z]+\*?", " ", s)  # any other macro
    s = s.replace("{", "").replace("}", "").replace("~", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s, bold


def clean_cell(raw: str) -> TexCell:
    """Clean one raw cell into text, first number, interval and bold flag.

    ``value`` is the first number when the cell starts with one (sign kept);
    ``None`` for ``---`` or text. ``interval`` is read from ``[lo, hi]``.
    """
    text, bold = _clean_text(raw)
    interval = None
    m = _INTERVAL.search(text)
    if m:
        interval = (float(m.group(1)), float(m.group(2)))
    head = _INTERVAL.sub("", text).strip()
    value = None
    if head and head not in ("---", "-", "--") and not head.startswith("---"):
        vm = re.match(r"^(" + _NUM + r")", head.replace(" ", "") if re.match(r"^[+-]\s", head) else head)
        if vm:
            value = float(vm.group(1))
    return TexCell(text=text, value=value, interval=interval, bold=bold, raw=raw)


def _split_unescaped(s: str, sep: str) -> list[str]:
    parts, buf, depth, i = [], [], 0, 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            buf.append(s[i : i + 2])
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


def _rows_of(body: str) -> list[str]:
    rows = re.split(r"\\\\(?:\s*\[[^\]]*\])?", body)
    return [r for r in rows if r.strip()]


def _strip_rules(row: str) -> str:
    row = re.sub(r"\\(?:midrule|toprule|bottomrule|hline)\b", "", row)
    row = re.sub(r"\\cmidrule(?:\([^)]*\))?\{[^}]*\}", "", row)
    return row.strip()


def _expand_multicolumn(cell: str) -> tuple[list[str], bool]:
    """A ``\\multicolumn{n}{..}{text}`` cell becomes n cells, text in the first."""
    s = cell.strip()
    s2 = re.sub(r"^\\rowcolor(?:\[[^\]]*\])?\{[^}]*\}", "", s).strip()
    if not s2.startswith("\\multicolumn"):
        return [cell], False
    k = len("\\multicolumn")
    n_s, k = _brace_arg(s2, k)
    _, k = _brace_arg(s2, k)
    content, k = _brace_arg(s2, k)
    try:
        n = int(n_s)
    except ValueError:
        n = 1
    return [content] + [""] * (n - 1), True


def _body(tabular: str) -> tuple[str, str]:
    """(header, body): the text before the first ``\\midrule`` and between it and ``\\bottomrule``."""
    end = tabular.find("\\bottomrule")
    if end < 0:
        end = len(tabular)
    start = tabular.find("\\midrule")
    if start < 0:
        return "", tabular[:end]
    return tabular[:start], tabular[start + len("\\midrule") : end]


def header_rows(tex: str) -> list[list[TexCell]]:
    """The header rows (before the first ``\\midrule``) of the first tabular in ``tex``."""
    tab = _tabular(tex)
    head, _ = _body(tab)
    begin = re.search(r"\\begin\{tabular\}(?:\{(?:[^{}]|\{[^{}]*\})*\})", head)
    if begin:
        head = head[begin.end() :]
    out = []
    for row in _rows_of(head):
        row = _strip_rules(row)
        if not row:
            continue
        cells: list[str] = []
        for c in _split_unescaped(row, "&"):
            cells.extend(_expand_multicolumn(c)[0])
        out.append([clean_cell(c) for c in cells])
    return out


def _tabular(tex: str) -> str:
    m = re.search(r"\\begin\{tabular\}", tex)
    if not m:
        return tex
    e = tex.find("\\end{tabular}", m.end())
    return tex[m.start() : e if e >= 0 else len(tex)]


def table_rows(tex: str) -> list[TexRow]:
    """Every data row between the first ``\\midrule`` and ``\\bottomrule``, with block titles.

    A row that is a single ``\\multicolumn`` spanning the table is a block
    title; it sets ``block`` for the rows below and is not returned.
    """
    tab = _tabular(tex)
    _, body = _body(tab)
    rows: list[TexRow] = []
    block = ""
    for raw in _rows_of(body):
        row = _strip_rules(raw)
        if not row:
            continue
        parts = _split_unescaped(row, "&")
        if len(parts) == 1:
            cells, was_multi = _expand_multicolumn(parts[0])
            if was_multi:
                block = clean_cell(cells[0]).text
                continue
        cells = []
        for c in parts:
            cells.extend(_expand_multicolumn(c)[0])
        rows.append(TexRow(cells=[clean_cell(c) for c in cells], block=block, raw=row))
    return rows


def table_by_label(tex: str, label: str) -> list[TexRow]:
    """The rows of the tabular in the table environment carrying ``\\label{<label>}``."""
    env = table_env(tex, label)
    return table_rows(env)


def table_env(tex: str, label: str) -> str:
    """The text of the table environment carrying ``\\label{<label>}``."""
    tex = strip_comments(tex)
    i = tex.find("\\label{" + label + "}")
    if i < 0:
        raise KeyError(f"no \\label{{{label}}} in the source")
    start = tex.rfind("\\begin{table", 0, i)
    end = tex.find("\\end{table", i)
    if start < 0:
        start = 0
    if end < 0:
        end = len(tex)
    return tex[start:end]


def read_table(path: Path, label: str | None = None) -> list[TexRow]:
    """Rows of a table file, or of the table labelled ``label`` inside it."""
    tex = strip_comments(Path(path).read_text(encoding="utf-8"))
    return table_by_label(tex, label) if label else table_rows(tex)


__all__ = [
    "TexCell",
    "TexRow",
    "clean_cell",
    "header_rows",
    "read_table",
    "strip_comments",
    "table_by_label",
    "table_env",
    "table_rows",
]
