"""The LaTeX table reader on the cell forms the paper's tables use."""

from __future__ import annotations

from pathlib import Path

import pytest

from toolform.advisor.texparse import (
    clean_cell,
    header_rows,
    read_table,
    strip_comments,
    table_by_label,
    table_env,
    table_rows,
)

FIXTURE = r"""
% a comment line
\begin{table}[t]
\caption{A caption with 5\% of text.}
\label{tab:selection}
\begin{tabular}{lrr}
\toprule
\textbf{Family} & \textbf{a} & \textbf{b} \\
\midrule
\rowcolor{ToolAccent!7}\multicolumn{3}{@{\hspace{3pt}}l}{\rule{0pt}{2.3ex}\textcolor{X}{\faServer}\enspace\textbf{First block}} \\
Qwen 3 & \cellcolor{ToolAccent!30}\textbf{77.7} & 1{,}315.4 \\
gpt-oss & $-3.28$ {\fontsize{6.2}{7}\selectfont [$-$6.18, $-$0.58]} & --- \\
\midrule
\multicolumn{3}{l}{Second block} \\
mean & 67.52\rank{1} & \texttt{xml\_call} \\
\bottomrule
\end{tabular}
\end{table}
"""


@pytest.mark.parametrize(
    "raw,text,value,interval,bold",
    [
        (r"\cellcolor{ToolAccent!33}86.7", "86.7", 86.7, None, False),
        (r"\textbf{67.52}\rank{1}", "67.52", 67.52, None, True),
        (r"$+13.80$ {\fontsize{6.2}{7}\selectfont [9.16, 18.72]}", "+13.80 [9.16, 18.72]", 13.8, (9.16, 18.72), False),
        (
            r"$-3.28$ {\fontsize{6.2}{7}\selectfont [$-$6.18, $-$0.58]}",
            "-3.28 [-6.18, -0.58]",
            -3.28,
            (-6.18, -0.58),
            False,
        ),
        (r"$-6.66$ {\scriptsize[-9.66, -3.90]}", "-6.66 [-9.66, -3.90]", -6.66, (-9.66, -3.9), False),
        ("---", "---", None, None, False),
        (r"\texttt{xml\_call}", "xml_call", None, None, False),
        (r"1{,}315.4", "1315.4", 1315.4, None, False),
        ("reference", "reference", None, None, False),
        (r"0.6--32", "0.6-32", 0.6, None, False),
        (r"{\scriptsize[47.20, 63.99]}", "[47.20, 63.99]", None, (47.2, 63.99), False),
        (r"$+17.08$\% over the whole panel", "+17.08 over the whole panel", 17.08, None, False),
    ],
)
def test_clean_cell(raw, text, value, interval, bold):
    c = clean_cell(raw)
    assert (c.text, c.value, c.interval, c.bold) == (text, value, interval, bold)


def test_rank_marker():
    assert clean_cell(r"\textbf{67.52}\rank{1}").rank == 1 and clean_cell("5").rank is None


def test_table_rows_and_blocks():
    rows = table_rows(strip_comments(FIXTURE))
    assert [r.texts()[0] for r in rows] == ["Qwen 3", "gpt-oss", "mean"]
    assert rows[0].block == "First block" and rows[2].block == "Second block"
    assert rows[0].cells[1].bold and rows[0].cells[2].value == 1315.4
    assert rows[1].cells[1].interval == (-6.18, -0.58) and rows[1].cells[2].value is None
    assert rows[2].cells[1].rank == 1 and rows[2].cells[2].text == "xml_call"


def test_header_and_label():
    assert [c.text for c in header_rows(FIXTURE)[-1]] == ["Family", "a", "b"]
    rows = table_by_label(FIXTURE, "tab:selection")
    assert len(rows) == 3
    assert "5\\%" in table_env(FIXTURE, "tab:selection")
    with pytest.raises(KeyError):
        table_by_label(FIXTURE, "tab:nope")


def test_strip_comments_keeps_escaped_percent():
    assert strip_comments("a 5\\% b % comment\nc") == "a 5\\% b \nc"


def test_read_table(tmp_path):
    p = tmp_path / "t.tex"
    p.write_text(FIXTURE)
    assert len(read_table(p)) == 3 and len(read_table(Path(p), "tab:selection")) == 3


def test_multicolumn_inside_a_row():
    tex = r"""\begin{tabular}{llr|lr}
\toprule
h & h & h & h & h \\
\midrule
\multicolumn{3}{l}{\textit{crossed}} & TypeScript & 45.74 \\
\bottomrule
\end{tabular}"""
    row = table_rows(tex)[0]
    assert row.texts() == ["crossed", "", "", "TypeScript", "45.74"]
