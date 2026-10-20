"""Printing: JSON for machines, rich tables and plain sentences for people."""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable, Mapping, Sequence

from rich.console import Console
from rich.markup import escape
from rich.table import Table


def console(*, stderr: bool = False) -> Console:
    """A console for the current stdout (or stderr). Off a terminal it is 120 columns wide, so lines do
    not wrap in logs and tests."""
    stream = sys.stderr if stderr else sys.stdout
    tty = hasattr(stream, "isatty") and stream.isatty()
    width = None if tty else int(os.environ.get("COLUMNS", "120") or 120)
    return Console(file=stream, width=width, highlight=False, soft_wrap=not tty, stderr=stderr)


def to_jsonable(obj: Any) -> Any:
    """``obj.to_dict()`` when it has one, else ``obj``."""
    return obj.to_dict() if hasattr(obj, "to_dict") else obj


def dumps(obj: Any) -> str:
    """Indented JSON of ``obj`` (or of its ``to_dict()``)."""
    return json.dumps(to_jsonable(obj), indent=2, ensure_ascii=False, default=str)


def emit(obj: Any, *, as_json: bool, render: Callable[[Any], None]) -> None:
    """Print ``obj`` as JSON and nothing else, or hand it to ``render`` for people."""
    if as_json:
        sys.stdout.write(dumps(obj) + "\n")
        sys.stdout.flush()
    else:
        render(obj)


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.2f}"
    if isinstance(v, (list, tuple)):
        return ", ".join(_cell(x) for x in v)
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def table(
    rows: Sequence[Mapping[str, Any]],
    columns: Sequence[str],
    *,
    title: str = "",
    headers: Sequence[str] | None = None,
    out: Console | None = None,
) -> None:
    """Print ``rows`` as a table of ``columns`` (``headers`` renames them)."""
    t = Table(title=title or None, title_justify="left", show_edge=False, header_style="bold", pad_edge=False)
    for i, c in enumerate(columns):
        t.add_column(headers[i] if headers else c, overflow="fold")
    for r in rows:
        t.add_row(*[escape(_cell(r.get(c))) for c in columns])
    (out or console()).print(t)


def say(text: str = "", *, style: str | None = None, markup: bool = False) -> None:
    """Print one line; user text is never read as markup unless asked."""
    console().print(text, style=style, markup=markup)


def error(text: str) -> None:
    """Print an error line to stderr."""
    console(stderr=True).print(f"error: {text}", style="red", markup=False)


def warn(text: str) -> None:
    """Print a warning line to stderr."""
    console(stderr=True).print(text, style="yellow", markup=False)


def pct(v: float | None, digits: int = 2) -> str:
    """``77.70%``; an empty string for None."""
    return "" if v is None else f"{v:.{digits}f}%"


__all__ = ["console", "dumps", "emit", "error", "escape", "pct", "say", "table", "to_jsonable", "warn"]
